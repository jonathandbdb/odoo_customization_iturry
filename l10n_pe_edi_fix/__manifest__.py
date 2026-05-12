# -*- coding: utf-8 -*-
{
    "name": "l10n_pe_edi_fix",
    "version": "19.0.1.0.3",
    "summary": "Parche para envío de comprobantes electrónicos SUNAT (Perú) en Odoo 19",
    "description": """
Parche del módulo Enterprise `l10n_pe_edi` para Odoo 19.

Corrige dos problemas detectados al intentar firmar/enviar comprobantes
a SUNAT/OSE:

1. `zeep.Client(...)` se instancia con los kwargs `operation_timeout` y
   `timeout`, que ya no son aceptados por zeep 4.x. Esto provoca un
   `TypeError` que es capturado por el `except` y se mapea al código
   genérico **L10NPE08** ("There was an error in the connection or the
   response from the OSE server"). El fix envuelve `zeep.Client` para
   redirigir esos kwargs a un `zeep.transports.Transport` interno.

2. El mapa de mensajes de error usa `_lt(...)` (LazyGettext). Al
   asignar ese valor al campo Html `account.edi.document.error`, el
   sanitizador HTML falla con `TypeError: expected string or
   bytes-like object, got 'LazyGettext'` y muestra en la UI el mensaje
   genérico "Unknown error when sanitizing", ocultando el error real.
   El fix coacciona los valores a `str` antes de ser usados.
    """,
    "category": "Accounting/Localizations/EDI",
    "license": "OPL-1",
    "depends": ["l10n_pe_edi"],
    "data": [],
    "installable": True,
    "application": False,
    "auto_install": True,
}
# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
