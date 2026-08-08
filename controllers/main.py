# -*- coding: utf-8 -*-
import hashlib
import hmac
import json
import logging
import time

from werkzeug.exceptions import Forbidden

from odoo import http
from odoo.http import request


_logger = logging.getLogger(__name__)


class AirwallexController(http.Controller):
    _webhook_url = '/payment/airwallex/webhook'
    _return_url = '/payment/airwallex/return'

    # Webhook timestamp 最大容許誤差。
    # 超過這個時間的 request 視為 replay / expired webhook。
    _webhook_tolerance_seconds = 300

    @http.route(
        _webhook_url,
        type='http',
        auth='public',
        methods=['POST'],
        csrf=False,
    )
    def airwallex_webhook(self):
        """
        處理 Airwallex Webhook 通知。

        Webhook 流程：
        1. Validate JSON structure
        2. Find corresponding Odoo transaction
        3. Verify HMAC signature + timestamp
        4. Ignore intermediate states
        5. Process payment state
        """
        raw_data = request.httprequest.data
        headers = request.httprequest.headers

        # =====================================================================
        # 1. Parse JSON
        # =====================================================================

        try:
            payload = json.loads(raw_data)

        except (TypeError, ValueError, json.JSONDecodeError):
            _logger.warning(
                "Airwallex Webhook: 無效的 JSON 資料"
            )

            return request.make_response(
                "Invalid JSON",
                headers=[
                    ('Content-Type', 'text/plain'),
                ],
                status=400,
            )

        if not isinstance(payload, dict):
            _logger.warning(
                "Airwallex Webhook: Payload 不是 JSON object"
            )

            return request.make_response(
                "Invalid JSON",
                headers=[
                    ('Content-Type', 'text/plain'),
                ],
                status=400,
            )

        # =====================================================================
        # 2. Extract event object
        # =====================================================================

        data = payload.get('data', {})

        if not isinstance(data, dict):
            _logger.warning(
                "Airwallex Webhook: data 格式錯誤"
            )

            return request.make_response(
                "Invalid payload",
                headers=[
                    ('Content-Type', 'text/plain'),
                ],
                status=400,
            )

        obj = data.get('object', {})

        if not isinstance(obj, dict):
            _logger.warning(
                "Airwallex Webhook: data.object 格式錯誤"
            )

            return request.make_response(
                "Invalid payload",
                headers=[
                    ('Content-Type', 'text/plain'),
                ],
                status=400,
            )

        # =====================================================================
        # Airwallex Webhook Event ID
        # =====================================================================
        #
        # Event ID 位於 payload 最外層：
        #
        # {
        #     "id": "evt_...",
        #     "name": "payment_intent.succeeded",
        #     "data": {
        #         "object": {...}
        #     }
        # }
        #
        # 注意：
        # payload["id"] 是 Webhook Event ID。
        #
        # data["object"]["id"] 則是 Payment Intent ID，
        # 兩者不能混用。
        #
        airwallex_event_id = payload.get('id')

        if airwallex_event_id:
            airwallex_event_id = str(airwallex_event_id)

        merchant_order_id = obj.get('merchant_order_id')
        status = (obj.get('status') or '').upper()

        if not merchant_order_id:
            _logger.warning(
                "Airwallex Webhook: 缺少 merchant_order_id"
            )

            return request.make_response(
                "Invalid payload",
                headers=[
                    ('Content-Type', 'text/plain'),
                ],
                status=400,
            )

        # Airwallex 可能使用 CANCELED，
        # module 內統一使用 CANCELLED。
        if status == 'CANCELED':
            status = 'CANCELLED'

        # =====================================================================
        # 3. Find Odoo transaction
        # =====================================================================
        #
        # 因為 webhook secret 是 provider-specific，
        # 必須先找到對應 provider 才能取得 webhook secret。
        #
        # 這裡只做 lookup，尚未修改任何 transaction state。
        #

        tx_sudo = request.env[
            'payment.transaction'
        ].sudo().search([
            ('reference', '=', merchant_order_id),
            ('provider_code', '=', 'airwallex'),
        ], limit=1)

        # 如果找不到交易，回 200 避免 Airwallex 不斷 retry。
        if not tx_sudo:
            _logger.warning(
                "Airwallex Webhook: 找不到交易 reference=%s",
                merchant_order_id,
            )

            return request.make_response(
                "OK",
                headers=[
                    ('Content-Type', 'text/plain'),
                ],
                status=200,
            )

        # =====================================================================
        # 4. Verify signature + timestamp
        # =====================================================================

        try:
            self._verify_signature(
                headers,
                raw_data,
                tx_sudo.provider_id,
            )

        except Forbidden as exc:
            _logger.warning(
                "Airwallex Webhook: 驗證失敗 "
                "reference=%s reason=%s",
                merchant_order_id,
                str(exc),
            )

            return request.make_response(
                "Forbidden",
                headers=[
                    ('Content-Type', 'text/plain'),
                ],
                status=403,
            )

        # =====================================================================
        # 5. Ignore intermediate states
        # =====================================================================

        if status in [
            'REQUIRES_PAYMENT_METHOD',
            'REQUIRES_CUSTOMER_ACTION',
            'PENDING',
        ]:
            _logger.info(
                "Airwallex Webhook: 忽略中間狀態 %s (Ref: %s)",
                status,
                merchant_order_id,
            )

            return request.make_response(
                "Ignored",
                headers=[
                    ('Content-Type', 'text/plain'),
                ],
                status=200,
            )

        # =====================================================================
        # 6. Process transaction
        # =====================================================================

        try:
            tx_sudo._process(
                'airwallex',
                {
                    'airwallex_obj': obj,
                    'airwallex_event_id': airwallex_event_id,
                },
            )

            _logger.info(
                "Airwallex Webhook: "
                "交易更新成功 reference=%s status=%s event_id=%s",
                merchant_order_id,
                status,
                airwallex_event_id,
            )

        except Exception:
            # 保留完整 traceback，方便 production debugging。
            _logger.exception(
                "Airwallex Webhook: 處理失敗 "
                "reference=%s event_id=%s",
                merchant_order_id,
                airwallex_event_id,
            )

            return request.make_response(
                "Internal Error",
                headers=[
                    ('Content-Type', 'text/plain'),
                ],
                status=500,
            )

        # =====================================================================
        # 7. Success
        # =====================================================================

        return request.make_response(
            "OK",
            headers=[
                ('Content-Type', 'text/plain'),
            ],
            status=200,
        )

    @classmethod
    def _verify_signature(cls, headers, raw_data, provider_sudo):
        """
        驗證 Airwallex Webhook signature。

        Airwallex signature：
            HMAC-SHA256(
                webhook_secret,
                timestamp + raw_body
            )

        同時檢查 timestamp，防止舊的合法 webhook 被 replay。
        """

        timestamp = headers.get('x-timestamp')
        signature = headers.get('x-signature')

        # ---------------------------------------------------------------------
        # Header validation
        # ---------------------------------------------------------------------

        if not timestamp or not signature:
            raise Forbidden("Missing signature")

        # ---------------------------------------------------------------------
        # Timestamp validation
        # ---------------------------------------------------------------------

        try:
            timestamp_value = int(timestamp)
        except (TypeError, ValueError):
            raise Forbidden("Invalid timestamp")

        # Airwallex 一般使用 Unix timestamp seconds。
        #
        # 如果收到 milliseconds，兼容處理，
        # 但簽名本身仍使用原始 timestamp string。
        timestamp_seconds = timestamp_value

        if timestamp_value > 10**11:
            timestamp_seconds = timestamp_value / 1000.0

        # 防止 replay attack。
        if abs(time.time() - timestamp_seconds) > cls._webhook_tolerance_seconds:
            raise Forbidden("Expired timestamp")

        # ---------------------------------------------------------------------
        # Webhook secret
        # ---------------------------------------------------------------------

        webhook_secret = provider_sudo.airwallex_webhook_secret

        if not webhook_secret:
            raise Forbidden(
                "Webhook secret is not configured"
            )

        # ---------------------------------------------------------------------
        # HMAC validation
        # ---------------------------------------------------------------------

        # Airwallex：
        #
        # timestamp + raw_body
        #
        # 使用原始 HTTP body，不能使用重新 json.dumps() 後的 JSON，
        # 否則 whitespace / encoding 改變會令 signature 不一致。
        signed_payload = (
            timestamp.encode('utf-8')
            + raw_data
        )

        expected_sig = hmac.new(
            webhook_secret.encode('utf-8'),
            msg=signed_payload,
            digestmod=hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(
            signature,
            expected_sig,
        ):
            raise Forbidden("Signature mismatch")

    @http.route(
        _return_url,
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
        save_session=False,
    )
    def airwallex_return(self, **data):
        """同步回調跳轉頁面 (User 回到網站)。"""
        return request.redirect('/payment/status')