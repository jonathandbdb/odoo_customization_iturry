# -*- coding: utf-8 -*-
import logging

from zeep import Client as _ZeepClient
from zeep.transports import Transport as _ZeepTransport

from odoo import api, models
from odoo.addons.l10n_pe_edi.models import account_edi_format as _aef

_logger = logging.getLogger(__name__)


# Comentario en español: wrapper que tolera la API antigua de zeep (operation_timeout / timeout)
# eliminada en zeep 4.x. Los redirige al Transport interno.
class _PatchedZeepClient(_ZeepClient):
    def __init__(self, *args, operation_timeout=None, timeout=None, transport=None, **kwargs):
        if transport is None and (operation_timeout is not None or timeout is not None):
            effective_timeout = timeout if timeout is not None else 15
            effective_op_timeout = operation_timeout if operation_timeout is not None else effective_timeout
            transport = _ZeepTransport(
                timeout=effective_timeout,
                operation_timeout=effective_op_timeout,
            )
        super().__init__(*args, transport=transport, **kwargs)


# Comentario en español: reemplazo en el namespace del módulo Enterprise.
# Los métodos del Enterprise referencian `Client` como nombre local; al
# parchar `_aef.Client` aquí todas las llamadas posteriores usan el wrapper.
if not getattr(_aef, "_l10n_pe_edi_fix_patched", False):
    _aef.Client = _PatchedZeepClient
    _aef._l10n_pe_edi_fix_patched = True
    _logger.info("l10n_pe_edi_fix: zeep.Client wrapped to support legacy operation_timeout/timeout kwargs.")


class AccountEdiFormat(models.Model):
    _inherit = "account.edi.format"

    @api.model
    def _l10n_pe_edi_get_general_error_messages(self):
        """
        Forzar evaluación de LazyGettext a str para evitar que el
        sanitizador HTML caiga en 'Unknown error when sanitizing' al
        recibir un objeto LazyGettext en un campo Html.
        """
        return {key: str(value) for key, value in super()._l10n_pe_edi_get_general_error_messages().items()}

    @api.model
    def _l10n_pe_edi_get_cdr_error_messages(self):
        """
        Idem: convertir LazyGettext a str para todos los códigos CDR.
        """
        return {key: str(value) for key, value in super()._l10n_pe_edi_get_cdr_error_messages().items()}

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
