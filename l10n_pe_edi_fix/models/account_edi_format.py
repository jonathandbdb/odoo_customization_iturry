# -*- coding: utf-8 -*-
import logging
import time
import traceback

from lxml import etree, objectify
from odoo.addons.l10n_pe_edi.models import account_edi_format as _aef
from odoo.tools import html_escape
from requests.exceptions import ConnectionError as ReqConnectionError
from requests.exceptions import HTTPError, ReadTimeout
from zeep import Client as _ZeepClient
from zeep import Settings
from zeep.transports import Transport as _ZeepTransport

from odoo import _, api, models

_logger = logging.getLogger(__name__)


# Comentario en español: el WAF de SUNAT responde intermitentemente 401
# al cargar los WSDLs importados (`billService?ns1.wsdl`,
# `billService.xsd2.xsd`). Reintentamos varias veces con backoff lineal.
class _RetryingTransport(_ZeepTransport):
    _MAX_RETRIES = 5
    _BACKOFF_BASE = 0.5

    def _load_remote_data(self, url):
        last_exc = None
        for attempt in range(self._MAX_RETRIES):
            try:
                return super()._load_remote_data(url)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                _logger.warning(
                    "l10n_pe_edi_fix: fallo cargando WSDL %s (intento %s/%s): %s",
                    url, attempt + 1, self._MAX_RETRIES, exc,
                )
                time.sleep(self._BACKOFF_BASE * (attempt + 1))
        raise last_exc

    def post(self, address, message, headers):
        # Comentario en español: SUNAT beta tambien responde 401 fugaz a la
        # llamada SOAP real. Reintentamos en ese caso (solo cuando el status
        # devuelto es 401 o 403; cualquier otro estado se entrega al caller
        # para que lo procese normalmente).
        last_response = None
        for attempt in range(self._MAX_RETRIES):
            response = super().post(address, message, headers)
            last_response = response
            if response.status_code not in (401, 403):
                return response
            _logger.warning(
                "l10n_pe_edi_fix: SUNAT POST %s respondio %s (intento %s/%s)",
                address, response.status_code, attempt + 1, self._MAX_RETRIES,
            )
            time.sleep(self._BACKOFF_BASE * (attempt + 1))
        return last_response


# Comentario en español: wrapper que tolera la API antigua de zeep
# (operation_timeout y timeout como kwargs de Client) eliminada en zeep
# 4.x, y usa el Transport con reintentos.
class _PatchedZeepClient(_ZeepClient):
    def __init__(self, *args, operation_timeout=None, timeout=None, transport=None, **kwargs):
        if transport is None:
            effective_timeout = timeout if timeout is not None else 15
            effective_op_timeout = operation_timeout if operation_timeout is not None else effective_timeout
            transport = _RetryingTransport(
                timeout=effective_timeout,
                operation_timeout=effective_op_timeout,
            )
        super().__init__(*args, transport=transport, **kwargs)


# Comentario en español: parche del Client en el namespace del módulo
# Enterprise para que todas las llamadas usen el wrapper.
if not getattr(_aef, "_l10n_pe_edi_fix_patched", False):
    _aef.Client = _PatchedZeepClient
    _aef._l10n_pe_edi_fix_patched = True
    _logger.info(
        "l10n_pe_edi_fix: zeep.Client wrapped (legacy kwargs + retrying transport)."
    )


class AccountEdiFormat(models.Model):
    _inherit = "account.edi.format"

    @api.model
    def _l10n_pe_edi_get_general_error_messages(self):
        """
        Forzar evaluación de LazyGettext a str para evitar que el
        sanitizador HTML caiga en 'Unknown error when sanitizing'.
        """
        return {key: str(value) for key, value in super()._l10n_pe_edi_get_general_error_messages().items()}

    @api.model
    def _l10n_pe_edi_get_cdr_error_messages(self):
        """
        Idem: convertir LazyGettext a str para todos los códigos CDR.
        """
        return {key: str(value) for key, value in super()._l10n_pe_edi_get_cdr_error_messages().items()}

    def _l10n_pe_edi_sign_service_sunat_digiflow_common(self, company, edi_filename, edi_str, credentials, latam_document_type):
        """
        Override del método del módulo Enterprise para reportar en el campo
        `error` la causa real cuando la conexión con SUNAT/Digiflow falla,
        en lugar de mostrar siempre el mensaje genérico L10NPE08.

        Mantiene el flujo original (firma + zip + sendBill) pero captura
        la excepción concreta y la incluye en el mensaje devuelto, de modo
        que el funcional pueda diagnosticar el problema (timeout, 401,
        TypeError de zeep, error de SOAP, etc.) sin tener que mirar logs.
        """
        if not company.sudo().l10n_pe_edi_certificate_id:
            return {"error": _("No valid certificate found for %s company.", company.display_name)}

        # Firma del documento (mismo flujo que el Enterprise).
        edi_tree = objectify.fromstring(edi_str)
        edi_tree = self._l10n_pe_sign(company.sudo().l10n_pe_edi_certificate_id, edi_tree)
        edi_str = etree.tostring(edi_tree, xml_declaration=True, encoding="ISO-8859-1")
        zip_edi_str = self._l10n_pe_edi_zip_edi_document([("%s.xml" % edi_filename, edi_str)])

        try:
            settings = Settings(raw_response=True)
            client = _aef.Client(
                wsdl=credentials["wsdl"],
                wsse=credentials["token"],
                settings=settings,
                operation_timeout=15,
                timeout=15,
            )
            result = client.service.sendBill("%s.zip" % edi_filename, zip_edi_str)
            # SUNAT responde 500 con un SOAP fault válido cuando la factura ya existe;
            # en ese caso queremos seguir decodificando la respuesta.
            if result.status_code != 500:
                result.raise_for_status()
        except (ReqConnectionError, HTTPError, TypeError, ReadTimeout) as exc:
            # Construir un mensaje informativo combinando el mensaje genérico
            # con el detalle técnico de la excepción para que el funcional
            # pueda actuar (reintentar, revisar credenciales, etc.).
            generic_msg = self._l10n_pe_edi_get_general_error_messages()["L10NPE08"]
            detail = "%s: %s" % (type(exc).__name__, str(exc))
            _logger.warning(
                "l10n_pe_edi_fix: fallo enviando %s a SUNAT/Digiflow:\n%s",
                edi_filename, traceback.format_exc(),
            )
            error_message = "%s<br/><br/><b>%s</b><br/>%s" % (
                generic_msg,
                _("Technical detail:"),
                html_escape(detail),
            )
            return {"error": error_message, "blocking_level": "warning"}

        soap_response = result.content
        soap_response_decoded = self._l10n_pe_edi_decode_soap_response(soap_response) if soap_response else {}

        if soap_response_decoded.get("error"):
            # Convertir a str por si el provider devuelve un LazyGettext.
            error_message = str(soap_response_decoded["error"])
            return {
                "error": error_message,
                "blocking_level": "error",
                "code": soap_response_decoded.get("code"),
                "xml_document": edi_str,
            }

        cdr = soap_response_decoded["cdr"]
        cdr_status = self._l10n_pe_edi_extract_cdr_status(cdr)

        if cdr_status["code"] != "0":
            error_message = "%s<br/><br/><b>%s</b>" % (
                cdr_status["description"],
                _("This document number is now registered by SUNAT as invalid."),
            )
            return {
                "error": error_message,
                "blocking_level": "error",
                "code": cdr_status["code"],
                "xml_document": edi_str,
            }

        return {"success": True, "xml_document": edi_str, "cdr": cdr}

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
