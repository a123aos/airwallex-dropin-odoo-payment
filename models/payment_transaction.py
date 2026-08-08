# -*- coding: utf-8 -*-
import json
import logging

from odoo import _, api, fields, models
from odoo.addons.payment_airwallex import const


_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    airwallex_client_secret = fields.Char(
        string="Airwallex Client Secret",
        groups='base.group_system',
    )

    airwallex_processed_event_ids = fields.Text(
        string="Airwallex Processed Webhook Event IDs",
        copy=False,
        groups='base.group_system',
        help=(
            "JSON list of Airwallex webhook event IDs "
            "that have already been processed."
        ),
    )

    # === 商業邏輯 - 預處理 ===

    def _get_specific_processing_values(self, processing_values):
        res = super()._get_specific_processing_values(processing_values)

        if self.provider_code != 'airwallex' or self.operation == 'online_token':
            return res

        # 確保前台 Public User 結帳時有權限將 Airwallex 金鑰寫入交易記錄，
        # 提權使用 .sudo()
        if not self.provider_reference or not self.airwallex_client_secret:
            intent_data = self.provider_id._airwallex_create_intent(self)

            self.sudo().write({
                'provider_reference': intent_data.get('intent_id'),
                'airwallex_client_secret': intent_data.get('client_secret'),
            })

        res.update({
            'client_secret': self.airwallex_client_secret,
            'intent_id': self.provider_reference,
            'currency': self.currency_id.name,
            'amount': self.amount,
            'airwallex_auto_capture': not self.provider_id.capture_manually,

            # Frontend 必須使用與 backend 相同的 Airwallex environment。
            # enabled = production，其他狀態 = demo。
            'airwallex_environment': (
                'prod'
                if self.provider_id.state == 'enabled'
                else 'demo'
            ),
        })

        # =========================================================================
        # === 【核心修正】刪除 api_url，避免 Odoo 傳統 POST / CSRF 流程介入 ========
        # =========================================================================
        #
        # Airwallex Drop-in 會自行處理 payment flow，
        # 因此不讓 Odoo PaymentForm 走傳統 api_url submit。
        #
        if 'api_url' in res:
            del res['api_url']

        return res

    # === 商業邏輯 - 核心狀態同步 ===

    def _process_notification_data(self, notification_data):
        if self.provider_code != 'airwallex':
            return super()._process_notification_data(notification_data)

        # 防併發：在處理前先鎖定該筆記錄。
        self.ensure_one()

        self.env.cr.execute(
            "SELECT id FROM payment_transaction WHERE id = %s FOR UPDATE",
            (self.id,),
        )

        # SQL row lock 取得後重新讀取欄位。
        #
        # 這一點對 Event ID idempotency 很重要：
        # 如果兩個 webhook request 幾乎同時進來，
        # 第二個 request 在等待 FOR UPDATE 後，
        # 必須讀取第一個 request 已經寫入的最新 event ID。
        self.invalidate_recordset([
            'state',
            'airwallex_processed_event_ids',
        ])

        airwallex_event_id = notification_data.get(
            'airwallex_event_id'
        )

        if airwallex_event_id:
            airwallex_event_id = str(airwallex_event_id)

            # =================================================================
            # Webhook Event Idempotency
            # =================================================================
            #
            # Airwallex webhook payload 最外層：
            #
            # "id": "evt_..."
            #
            # 同一個 webhook event retry 時，
            # event ID 保持不變。
            #
            # 因此：
            #
            # 第一次：
            #     event_id 不存在 -> 正常處理
            #
            # 第二次：
            #     event_id 已存在 -> 直接忽略
            #
            processed_event_ids = (
                self._get_processed_airwallex_event_ids()
            )

            if airwallex_event_id in processed_event_ids:
                _logger.info(
                    "Airwallex: 忽略重複 webhook "
                    "event_id=%s reference=%s",
                    airwallex_event_id,
                    self.reference,
                )
                return

        _logger.info(
            "Airwallex: 處理通知資料 "
            "transaction=%s event_id=%s",
            self.reference,
            airwallex_event_id,
        )

        # 保留現有 payment state processing。
        self._apply_updates(notification_data)

        # =====================================================================
        # Mark event as processed
        # =====================================================================
        #
        # 只有 _apply_updates() 正常返回後才記錄 event ID。
        #
        # 如果 _apply_updates() 拋出 exception：
        #     不會記錄 event ID
        #     Airwallex 可以 retry
        #
        if airwallex_event_id:
            processed_event_ids = (
                self._get_processed_airwallex_event_ids()
            )

            if airwallex_event_id not in processed_event_ids:
                processed_event_ids.append(airwallex_event_id)

            # 避免 transaction 上的 JSON list 無限增長。
            #
            # 一般 payment transaction 不會有大量 webhook events，
            # 但仍限制最多保存最近 50 個 event IDs。
            processed_event_ids = processed_event_ids[-50:]

            self.sudo().write({
                'airwallex_processed_event_ids': json.dumps(
                    processed_event_ids
                ),
            })

    def _get_processed_airwallex_event_ids(self):
        """
        取得已處理的 Airwallex webhook event IDs。

        如果資料不存在或格式損壞，安全地回傳空 list。
        """
        self.ensure_one()

        if not self.airwallex_processed_event_ids:
            return []

        try:
            processed_event_ids = json.loads(
                self.airwallex_processed_event_ids
            )

        except (TypeError, ValueError, json.JSONDecodeError):
            _logger.warning(
                "Airwallex: 無法解析已處理 event IDs reference=%s",
                self.reference,
            )
            return []

        if not isinstance(processed_event_ids, list):
            _logger.warning(
                "Airwallex: 已處理 event IDs 格式錯誤 reference=%s",
                self.reference,
            )
            return []

        return [
            str(event_id)
            for event_id in processed_event_ids
            if event_id
        ]

    def _apply_updates(self, notification_data):
        if self.provider_code != 'airwallex':
            return super()._apply_updates(notification_data)

        air_obj = notification_data.get('airwallex_obj', {})
        status = (air_obj.get('status') or '').upper()

        # Airwallex 某些 response/event 可能使用 CANCELED，
        # Odoo / 本 module 內統一使用 CANCELLED。
        if status == 'CANCELED':
            status = 'CANCELLED'

        # 處理初始狀態：
        # 如果是初始意圖建立或瀏覽狀態，保持 Draft。
        if (
            status in [
                'REQUIRES_PAYMENT_METHOD',
                'REQUIRES_CUSTOMER_ACTION',
            ]
            and self.state == 'draft'
        ):
            _logger.info(
                "Airwallex: 偵測到 Intent 預備狀態 %s，"
                "維持 Draft，不變更訂單。",
                status,
            )
            return

        mapping = (
            const.REFUND_STATUS_MAPPING
            if self.operation == 'refund'
            else const.PAYMENT_STATUS_MAPPING
        )

        new_state = mapping.get(status)

        # 未知 status 不應該修改 Odoo transaction。
        if new_state is None:
            _logger.warning(
                "Airwallex: 未知 webhook status=%s reference=%s",
                status,
                self.reference,
            )
            return

        # 狀態相同時跳過。
        if self.state == new_state:
            return

        # 購物車保護：
        # payment 尚未完成時，未知/失敗狀態不要直接把 transaction cancel/error。
        if (
            new_state in ['cancel', 'error']
            and self.state in ['draft', 'pending']
        ):
            return

        # 正常狀態流轉。
        if new_state == 'done':
            self._set_done()

        elif new_state == 'pending':
            self._set_pending()

        elif new_state == 'authorized':
            self._set_authorized()

        elif new_state == 'cancel':
            self._set_canceled()

        elif new_state == 'error':
            self._set_error(
                _("Airwallex 交易處理錯誤: %s") % status
            )

        # 觸發後續核銷。
        if self.operation == 'refund' and self.state == 'done':
            self.env.ref(
                'payment.cron_post_process_payment_tx'
            )._trigger()

    # === 商業邏輯 - 輔助工具 ===

    @api.model
    def _search_by_reference(self, provider_code, payment_data):
        if provider_code != 'airwallex':
            return super()._search_by_reference(
                provider_code,
                payment_data,
            )

        air_obj = payment_data.get('airwallex_obj', {})

        # 優先使用 Airwallex provider reference / intent id。
        provider_ref = air_obj.get('id')

        if provider_ref:
            tx = self.search([
                ('provider_reference', '=', provider_ref),
                ('provider_code', '=', 'airwallex'),
            ], limit=1)

            if tx:
                return tx

        # Fallback 使用 Odoo reference / merchant_order_id。
        reference = (
            payment_data.get('reference')
            or air_obj.get('merchant_order_id')
        )

        if not reference:
            return self.env['payment.transaction']

        return self.search([
            ('reference', '=', reference),
            ('provider_code', '=', 'airwallex'),
        ], limit=1)

    def _extract_amount_data(self, payment_data):
        if self.provider_code != 'airwallex':
            return super()._extract_amount_data(payment_data)

        air_obj = payment_data.get('airwallex_obj', {})

        # 安全解析：
        # API 沒有 amount 時回退使用 transaction amount。
        #
        # 這裡仍使用 Odoo payment framework 預期的 numeric amount，
        # 避免 Decimal / float 混用導致後續 framework 比較出錯。
        raw_amount = air_obj.get('amount')

        try:
            amount = (
                abs(float(raw_amount))
                if raw_amount is not None
                else self.amount
            )
        except (TypeError, ValueError):
            _logger.warning(
                "Airwallex: 無法解析 amount=%r，"
                "改用交易金額 reference=%s",
                raw_amount,
                self.reference,
            )
            amount = self.amount

        currency_code = (
            air_obj.get('currency')
            or self.currency_id.name
        )

        return {
            'amount': amount,
            'currency_code': currency_code.upper(),
        }