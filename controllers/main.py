# -*- coding: utf-8 -*-
import logging
import json
import hmac
import hashlib
from werkzeug.exceptions import Forbidden
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

class AirwallexController(http.Controller):
    _webhook_url = '/payment/airwallex/webhook'
    _return_url = '/payment/airwallex/return'

    @http.route(_webhook_url, type='http', auth='public', methods=['POST'], csrf=False)
    def airwallex_webhook(self):
        """
        處理 Airwallex Webhook 通知
        這是與 Airwallex 伺服器直接對接的入口，必須確保回應格式完全符合要求
        """
        raw_data = request.httprequest.data
        headers = request.httprequest.headers
        
        # 1. 解析 Payload (必須確保 JSON 格式正確)
        try:
            payload = json.loads(raw_data)
        except Exception:
            _logger.error("Airwallex Webhook: 無效的 JSON 資料")
            return request.make_response("Invalid JSON", headers=[('Content-Type', 'text/plain')], status=400)

        obj = payload.get('data', {}).get('object', {})
        merchant_order_id = obj.get('merchant_order_id')
        status = obj.get('status', '').upper()
        
        # 2. 查找對應交易 (確保該訂單在 Odoo 中存在)
        tx_sudo = request.env['payment.transaction'].sudo().search([
            ('reference', '=', merchant_order_id),
            ('provider_code', '=', 'airwallex'),
        ], limit=1)

        # 即使找不到交易，也要回 200，否則 Airwallex 會持續重試
        if not tx_sudo:
            _logger.warning("Airwallex Webhook: 找不到交易 reference=%s", merchant_order_id)
            return request.make_response("OK", headers=[('Content-Type', 'text/plain')], status=200)

        # 3. 簽名驗證 (確保請求來自 Airwallex，防止惡意攻擊)
        try:
            self._verify_signature(headers, raw_data, tx_sudo.provider_id)
        except Forbidden:
            _logger.error("Airwallex Webhook: 簽名驗證失敗 reference=%s", merchant_order_id)
            return request.make_response("Forbidden", headers=[('Content-Type', 'text/plain')], status=403)

        # 4. 狀態過濾 (避免不必要的處理導致資料庫衝突)
        # 這些是中間狀態，對於訂單確認沒有實際意義
        if status in ['REQUIRES_PAYMENT_METHOD', 'REQUIRES_CUSTOMER_ACTION', 'PENDING']:
            _logger.info("Airwallex Webhook: 忽略中間狀態 %s (Ref: %s)", status, merchant_order_id)
            return request.make_response("Ignored", headers=[('Content-Type', 'text/plain')], status=200)

        # 5. 呼叫模型處理業務邏輯 (這是將支付狀態同步到 Odoo 的核心)
        try:
            # 這裡呼叫後端模型的方法
            tx_sudo._process('airwallex', {'airwallex_obj': obj})
            _logger.info("Airwallex Webhook: 交易更新成功: %s", merchant_order_id)
        except Exception as e:
            _logger.error("Airwallex Webhook: 處理失敗 %s: %s", merchant_order_id, str(e))
            return request.make_response("Internal Error", headers=[('Content-Type', 'text/plain')], status=500)
        
        # 最終成功回應
        return request.make_response("OK", headers=[('Content-Type', 'text/plain')], status=200)

    @staticmethod
    def _verify_signature(headers, raw_data, provider_sudo):
        """驗證 Airwallex Webhook 簽名規範"""
        timestamp = headers.get('x-timestamp')
        signature = headers.get('x-signature')
        
        if not timestamp or not signature:
            raise Forbidden("Missing signature")

        webhook_secret = provider_sudo.airwallex_webhook_secret
        # Airwallex 簽名計算規範：timestamp + raw_body
        signed_payload = f"{timestamp}{raw_data.decode('utf-8')}".encode('utf-8')
        
        expected_sig = hmac.new(
            webhook_secret.encode('utf-8'),
            msg=signed_payload,
            digestmod=hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(signature, expected_sig):
            raise Forbidden("Signature mismatch")

    @http.route(_return_url, type='http', auth='public', methods=['GET'], csrf=False, save_session=False)
    def airwallex_return(self, **data):
        """同步回調跳轉頁面 (User 回到網站)"""
        return request.redirect('/payment/status')