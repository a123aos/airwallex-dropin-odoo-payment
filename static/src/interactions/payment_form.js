/** @odoo-module **/

import { loadJS } from '@web/core/assets';
import { _t } from '@web/core/l10n/translation';
import { PaymentForm } from '@payment/interactions/payment_form';
import { patch } from '@web/core/utils/patch';

patch(PaymentForm.prototype, {

    setup() {
        super.setup();
        this.airwallexDropIn = null;
        this.airwallexLoaded = false;
        console.log("Airwallex: setup 執行完成");
    },

    async _processRedirectFlow(providerCode, paymentOptionId, paymentMethodCode, processingValues) {
        if (providerCode === 'airwallex') {
            console.log("Airwallex: 進入 RedirectFlow");
            return this._processDirectFlow(...arguments);
        }
        return super._processRedirectFlow(...arguments);
    },

    async _processDirectFlow(providerCode, paymentOptionId, paymentMethodCode, processingValues) {
        if (providerCode !== 'airwallex') {
            return super._processDirectFlow(...arguments);
        }

        console.log("Airwallex: 進入 DirectFlow, 狀態 airwallexLoaded:", this.airwallexLoaded);

        try {
            // 1. 初始化 SDK
            if (!this.airwallexLoaded) {
                console.log("Airwallex: 開始執行 loadJS...");
                await loadJS('https://static.airwallex.com/components/sdk/v1/index.js');
                console.log("Airwallex: loadJS 載入完成，window 物件狀態:", !!window.AirwallexComponentsSDK);
                
                const env = 'prod';
                console.log("Airwallex: 開始執行 init, 環境:", env);
                
                await window.AirwallexComponentsSDK.init({
                    env: env,
                    enabledElements: ['payments'],
                });
                console.log("Airwallex: init 初始化成功");
                this.airwallexLoaded = true;
            } else {
                console.log("Airwallex: SDK 已載入，跳過初始化");
            }

            // 2. 獲取容器
            const container = document.getElementById('dropIn');
            console.log("Airwallex: 檢查容器 #dropIn:", container);
            if (!container) {
                throw new Error(_t("找不到支付容器 #dropIn"));
            }

            // 3. 銷毀舊實例
            if (this.airwallexDropIn) {
                console.log("Airwallex: 銷毀舊實例");
                this.airwallexDropIn.destroy();
                this.airwallexDropIn = null;
            }

            // 4. 建立 Drop-in 設定
            const currency = processingValues['currency'];
            console.log("Airwallex: 準備建立元件, 幣種:", currency, "IntentID:", processingValues['intent_id']);
            const options = {
                intent_id: processingValues['intent_id'],
                client_secret: processingValues['client_secret'],
                currency: currency,
                country_code: 'HK',
            };

            if (currency === 'HKD') {
                options.methods = ['wechatpay', 'payme'];
            } else if (currency === 'CNY') {
                options.methods = ['wechatpay'];
            }

            // 5. 建立並掛載 Drop-in
            console.log("Airwallex: 呼叫 createElement...");
            this.airwallexDropIn = await window.AirwallexComponentsSDK.createElement('dropIn', options);
            console.log("Airwallex: createElement 完成，準備執行 mount");
            this.airwallexDropIn.mount('dropIn');
            console.log("Airwallex: mount 完成");

            // 6. 事件處理
            this.airwallexDropIn.on('ready', () => {
                console.log('Airwallex: Drop-in is ready');
            });

            this.airwallexDropIn.on('success', (event) => {
                console.log('Airwallex: 支付成功');
                window.location = '/payment/status';
            });

            this.airwallexDropIn.on('error', (event) => {
                console.error('Airwallex: 支付錯誤', event);
                this._displayErrorDialog(
                    _t("支付失敗"),
                    event.error?.message || _t("交易發生錯誤")
                );
                this._enableButton();
            });

        } catch (err) {
            console.error("Airwallex: 發生異常:", err);
            this._displayErrorDialog(_t("初始化錯誤"), err.message);
            this._enableButton();
        }
    }
});