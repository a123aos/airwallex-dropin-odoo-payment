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
        selection_add=[('airwallex', "Airwallex")], ondelete={'airwallex': 'set default'})
    
    # === 憑據配置 ===
    airwallex_client_id = fields.Char(string="Airwallex Client ID", groups='base.group_system')
    airwallex_api_key = fields.Char(string="Airwallex API Key", groups='base.group_system')
    airwallex_webhook_secret = fields.Char(string="Airwallex Webhook Secret", groups='base.group_system', copy=False)

    # === Token 緩存機制 ===
    airwallex_access_token = fields.Char(groups='base.group_system', copy=False)
    airwallex_token_expiry = fields.Datetime(groups='base.group_system', copy=False)

    # === 核心業務邏輯：建立或取得支付意向 ===
    def _airwallex_create_intent(self, transaction):
        """
        統一入口：處理支付意向建立，並加入冪等性檢查 (Idempotency)。
        """
        self.ensure_one()

        # 1. 冪等性檢查：如果已經有 Intent ID，則查詢狀態而非建立
        if transaction.provider_reference:
            _logger.info("Airwallex: 交易 %s 已存在 Intent，查詢狀態中...", transaction.reference)
            res = self._airwallex_make_request(f'pa/payment_intents/{transaction.provider_reference}', method='GET')
            # 【關鍵修復】確保查詢現有 Intent 時，回傳給 transaction.py 的字典結構與新建時完全對齊
            return {
                'intent_id': res.get('id'),
                'client_secret': res.get('client_secret'),
            }

        # 2. 建立新 Intent
        payload = {
            'request_id': f"INTENT_{transaction.reference}_{uuid.uuid4().hex[:6]}",
            'amount': float(transaction.amount),
            'currency': transaction.currency_id.name.upper(),
            'merchant_order_id': transaction.reference,
            'return_url': f"{self.get_base_url().rstrip('/')}/payment/airwallex/return",
            'metadata': {'odoo_transaction_id': transaction.id},
        }
        
        _logger.info("Airwallex: 建立新 Intent 給交易 %s", transaction.reference)
        res = self._airwallex_make_request('pa/payment_intents/create', payload=payload)
        
        # 3. 回傳精簡後的資訊給前端 (Drop-in UI)
        return {
            'intent_id': res.get('id'),
            'client_secret': res.get('client_secret'),
        }

    # === API 通訊核心 ===
    def _airwallex_get_api_url(self, endpoint=None):
        base_url = 'https://api.airwallex.com/api/v1/' if self.state == 'enabled' else 'https://api-demo.airwallex.com/api/v1/'
        return f"{base_url}{endpoint.lstrip('/')}" if endpoint else base_url

    def _airwallex_get_access_token(self):
        self.ensure_one()
        now = Datetime.now()
        if self.airwallex_access_token and self.airwallex_token_expiry:
            if now + timedelta(minutes=5) < self.airwallex_token_expiry:
                return self.airwallex_access_token

        url = self._airwallex_get_api_url('authentication/login')
        headers = {'x-client-id': self.airwallex_client_id, 'x-api-key': self.airwallex_api_key}
        
        try:
            response = requests.post(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            self.sudo().write({
                'airwallex_access_token': data.get('token'),
                'airwallex_token_expiry': dateutil_parser.parse(data.get('expires_at')).replace(tzinfo=None)
            })
            return data.get('token')
        except Exception as e:
            _logger.error("Airwallex Auth Failed: %s", e)
            raise ValidationError(_("Airwallex 身份驗證失敗。"))

    def _airwallex_make_request(self, endpoint, method='POST', payload=None):
        self.ensure_one()
        url = self._airwallex_get_api_url(endpoint)
        token = self._airwallex_get_access_token()
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        
        try:
            response = requests.request(method, url, json=payload, headers=headers, timeout=15)
            if not response.ok:
                _logger.error("Airwallex API Error (%s): %s", endpoint, response.text)
                raise ValidationError(_("Airwallex 請求失敗: %s" % response.text))
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
        webhook_url = f"{self.get_base_url().rstrip('/')}/payment/airwallex/webhook"
        payload = {
            'url': webhook_url,
            'version': '2023-11-01',
            'events': const.SUPPORTED_WEBHOOK_EVENTS,
            'request_id': str(uuid.uuid4()),
        }
        webhook_data = self._airwallex_make_request('webhooks/create', payload=payload)
        self.sudo().write({'airwallex_webhook_secret': webhook_data.get('secret')})
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {'message': _("Airwallex Webhook 建立成功！"), 'type': 'info'}}
