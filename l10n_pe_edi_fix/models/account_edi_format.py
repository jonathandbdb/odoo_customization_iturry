# -*- coding: utf-8 -*-
import logging
import time

from zeep import Client as _ZeepClient
from zeep.transports import Transport as _ZeepTransport

from odoo import api, models
from odoo.addons.l10n_pe_edi.models import account_edi_format as _aef

_logger = logging.getLogger(__name__)


# Comentario en español: el WAF de SUNAT responde intermitentemente 401
# al cargar el WSDL importado (`billService?ns1.wsdl`). Reintentamos.
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


# Comentario en español: reemplazo en el namespace del módulo Enterprise.
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

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
