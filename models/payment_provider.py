# -*- coding: utf-8 -*-
import logging
import requests
import uuid
from datetime import timedelta
from dateutil import parser as dateutil_parser

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Datetime

from odoo.addons.payment_airwallex import const

_logger = logging.getLogger(__name__)


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    code = fields.Selection(
        selection_add=[('airwallex', "Airwallex")],
        ondelete={'airwallex': 'set default'},
    )

    # === 憑據配置 ===
    airwallex_client_id = fields.Char(
        string="Airwallex Client ID",
        groups='base.group_system',
    )
    airwallex_api_key = fields.Char(
        string="Airwallex API Key",
        groups='base.group_system',
    )
    airwallex_webhook_secret = fields.Char(
        string="Airwallex Webhook Secret",
        groups='base.group_system',
        copy=False,
    )

    # === Token 緩存機制 ===
    airwallex_access_token = fields.Char(
        groups='base.group_system',
        copy=False,
    )
    airwallex_token_expiry = fields.Datetime(
        groups='base.group_system',
        copy=False,
    )

    def _airwallex_create_intent(self, transaction):
        """
        統一入口：處理支付意向建立，包含過期檢查與國家代碼動態注入。

        The shopper country is taken from the Odoo transaction partner when
        available. It is never guessed as HK: HK is the merchant's country,
        not the shopper's country.
        """
        self.ensure_one()

        # 1. Shopper country.
        #    Do not use HK as a fallback: Airwallex's Drop-in country_code is
        #    shopper-related, while Apple Pay's merchant country is handled
        #    separately in the frontend.
        country_code = False
        if transaction.sale_order_ids:
            order = transaction.sale_order_ids[0]
            partner = order.partner_shipping_id or order.partner_id
            if partner and partner.country_id:
                country_code = partner.country_id.code or False
        elif transaction.partner_id and transaction.partner_id.country_id:
            country_code = transaction.partner_id.country_id.code or False

        # 2. 冪等性與過期檢查：如果已有 reference，查詢狀態
        if transaction.provider_reference:
            _logger.info(
                "Airwallex: 交易 %s 已存在 Intent，查詢狀態中...",
                transaction.reference,
            )
            intent_data = self._airwallex_make_request(
                f'pa/payment_intents/{transaction.provider_reference}',
                method='GET',
            )

            # 如果狀態已失效，清除 reference 觸發後續重建
            if intent_data.get('status') in ['EXPIRED', 'CANCELED']:
                _logger.info(
                    "Airwallex: 發現過期 Intent %s，準備重新建立",
                    transaction.provider_reference,
                )
                transaction.write({'provider_reference': False})
            else:
                return {
                    'intent_id': intent_data.get('id'),
                    'client_secret': intent_data.get('client_secret'),
                    'country_code': country_code,
                }

        # 3. 建立新 Intent
        payload = {
            'request_id': f"INTENT_{transaction.reference}_{uuid.uuid4().hex[:6]}",
            'amount': round(float(transaction.amount), 2),
            'currency': transaction.currency_id.name.upper(),
            'merchant_order_id': transaction.reference,
            'return_url': f"{self.get_base_url().rstrip('/')}/payment/airwallex/return",
            'metadata': {'odoo_transaction_id': transaction.id},
        }

        # Only send the shopper country when Odoo actually knows it.
        # Never invent HK here.
        if country_code:
            payload['customer'] = {
                'address': {'country_code': country_code}
            }

        _logger.info(
            "Airwallex: 建立新 Intent (Shopper Country: %s) 給交易 %s",
            country_code or 'not provided',
            transaction.reference,
        )
        res = self._airwallex_make_request(
            'pa/payment_intents/create',
            payload=payload,
        )

        # 將新的 provider_reference 寫回 Odoo 交易記錄
        transaction.write({'provider_reference': res.get('id')})

        return {
            'intent_id': res.get('id'),
            'client_secret': res.get('client_secret'),
            'country_code': country_code,
        }

    # === API 通訊核心 ===
    def _airwallex_get_api_url(self, endpoint=None):
        base_url = (
            'https://api.airwallex.com/api/v1/'
            if self.state == 'enabled'
            else 'https://api-demo.airwallex.com/api/v1/'
        )
        return f"{base_url}{endpoint.lstrip('/')}" if endpoint else base_url

    def _airwallex_get_access_token(self):
        self.ensure_one()
        now = Datetime.now()
        if self.airwallex_access_token and self.airwallex_token_expiry:
            if now + timedelta(minutes=5) < self.airwallex_token_expiry:
                return self.airwallex_access_token

        url = self._airwallex_get_api_url('authentication/login')
        headers = {
            'x-client-id': self.airwallex_client_id,
            'x-api-key': self.airwallex_api_key,
        }

        try:
            response = requests.post(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            self.sudo().write({
                'airwallex_access_token': data.get('token'),
                'airwallex_token_expiry': dateutil_parser.parse(
                    data.get('expires_at')
                ).replace(tzinfo=None),
            })
            return data.get('token')
        except Exception as e:
            _logger.error("Airwallex Auth Failed: %s", e)
            raise ValidationError(_("Airwallex 身份驗證失敗。"))

    def _airwallex_make_request(self, endpoint, method='POST', payload=None):
        self.ensure_one()
        url = self._airwallex_get_api_url(endpoint)
        token = self._airwallex_get_access_token()
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        }

        try:
            response = requests.request(
                method,
                url,
                json=payload,
                headers=headers,
                timeout=15,
            )
            if not response.ok:
                _logger.error(
                    "Airwallex API Error (%s): %s",
                    endpoint,
                    response.text,
                )
                raise ValidationError(
                    _("Airwallex 請求失敗: %s" % response.text)
                )
            return response.json()
        except requests.exceptions.RequestException as e:
            _logger.error("Airwallex Network Error: %s", e)
            raise ValidationError(_("無法連接至 Airwallex 伺服器。"))

    # === 功能配置 ===
    def _compute_feature_support_fields(self):
        super()._compute_feature_support_fields()
        self.filtered(lambda p: p.code == 'airwallex').update({
            'support_refund': 'partial',
            'support_tokenization': True,
        })

    def action_airwallex_create_webhook(self):
        self.ensure_one()
        webhook_url = (
            f"{self.get_base_url().rstrip('/')}/payment/airwallex/webhook"
        )
        payload = {
            'url': webhook_url,
            'version': '2023-11-01',
            'events': const.SUPPORTED_WEBHOOK_EVENTS,
            'request_id': str(uuid.uuid4()),
        }
        webhook_data = self._airwallex_make_request(
            'webhooks/create',
            payload=payload,
        )
        self.sudo().write({
            'airwallex_webhook_secret': webhook_data.get('secret')
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': _("Airwallex Webhook 建立成功！"),
                'type': 'info',
            },
        }
