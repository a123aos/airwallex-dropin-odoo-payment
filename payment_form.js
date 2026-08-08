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
        this.airwallexEnvironment = null;
    },

    async _processRedirectFlow(
        providerCode,
        paymentOptionId,
        paymentMethodCode,
        processingValues
    ) {
        if (providerCode === 'airwallex') {
            return this._processDirectFlow(...arguments);
        }

        return super._processRedirectFlow(...arguments);
    },

    async _processDirectFlow(
        providerCode,
        paymentOptionId,
        paymentMethodCode,
        processingValues
    ) {
        if (providerCode !== 'airwallex') {
            return super._processDirectFlow(...arguments);
        }

        try {
            // =================================================================
            // 1. Airwallex environment
            // =================================================================
            //
            // 不再 hard-code：
            //
            //     const env = 'prod';
            //
            // Backend 現在會傳：
            //
            //     airwallex_environment = 'prod'
            //     或
            //     airwallex_environment = 'demo'
            //
            // 因此 test transaction 不會意外使用 production SDK。
            //

            const env =
                processingValues['airwallex_environment']
                || 'demo';


            // =================================================================
            // 2. Initialize Airwallex SDK
            // =================================================================

            if (!this.airwallexLoaded) {

                await loadJS(
                    'https://static.airwallex.com/components/sdk/v1/index.js'
                );

                if (!window.AirwallexComponentsSDK) {
                    throw new Error(
                        _t("Airwallex SDK 載入失敗")
                    );
                }

                await window.AirwallexComponentsSDK.init({
                    env: env,
                    enabledElements: ['payments'],
                });

                this.airwallexLoaded = true;
                this.airwallexEnvironment = env;

            } else if (
                this.airwallexEnvironment !== env
            ) {

                // 同一 PaymentForm instance 不應該在 SDK 已初始化後
                // 再切換 demo / production。
                //
                // 如果發生，通常代表 frontend/backend environment
                // processing values 不一致。
                throw new Error(
                    _t(
                        "Airwallex 支付環境與目前交易不一致，請重新載入頁面"
                    )
                );
            }


            // =================================================================
            // 3. Find Drop-in container
            // =================================================================
            //
            // 保留目前 template 使用的 #dropIn，
            // 所以不需要另外修改 XML template。
            //

            const container =
                this.el?.querySelector('#dropIn')
                || document.getElementById('dropIn');

            if (!container) {
                throw new Error(
                    _t("找不到支付容器 #dropIn")
                );
            }


            // =================================================================
            // 4. Destroy previous Drop-in
            // =================================================================

            if (this.airwallexDropIn) {
                this.airwallexDropIn.destroy();
                this.airwallexDropIn = null;
            }


            // =================================================================
            // 5. Payment configuration
            // =================================================================

            const currency =
                processingValues['currency'];

            const countryCode =
                processingValues['country_code']
                || 'HK';


            // 指定不同 currency 的 payment methods。
            const methodMapping = {
                'HKD': [
                    'card',
                    'wechatpay',
                    'payme',
                ],

                'CNY': [
                    'wechatpay',
                ],

                'SGD': [
                    'pay_now',
                    'wechatpay',
                ],

                'KRW': [
                    'kakaopay',
                    'wechatpay',
                ],
            };


            const options = {
                intent_id:
                    processingValues['intent_id'],

                client_secret:
                    processingValues['client_secret'],

                currency:
                    currency,

                country_code:
                    countryCode,

                applePayRequestOptions: {
                    countryCode:
                        countryCode,

                    buttonType:
                        'buy',

                    buttonColor:
                        'black',
                },
            };


            if (methodMapping[currency]) {
                options.methods =
                    methodMapping[currency];
            }


            // =================================================================
            // 6. Create Drop-in
            // =================================================================

            this.airwallexDropIn =
                await window.AirwallexComponentsSDK.createElement(
                    'dropIn',
                    options,
                );


            // 保留原本 SDK 使用的 selector，
            // 避免因 mount API 行為差異造成 regression。
            this.airwallexDropIn.mount('dropIn');


            // =================================================================
            // 7. Event handling
            // =================================================================

            this.airwallexDropIn.on(
                'ready',
                () => {
                    // Production 不需要輸出 debug log。
                }
            );


            this.airwallexDropIn.on(
                'success',
                () => {
                    window.location =
                        '/payment/status';
                }
            );


            this.airwallexDropIn.on(
                'error',
                (event) => {

                    const message =
                        event?.error?.message
                        || _t("交易發生錯誤");

                    // Error 保留，但不輸出完整 event，
                    // 避免 payment-related data 被 dump 到 browser console。
                    console.error(
                        'Airwallex payment error:',
                        message
                    );

                    this._displayErrorDialog(
                        _t("支付失敗"),
                        message,
                    );

                    this._enableButton();
                }
            );

        } catch (err) {

            console.error(
                'Airwallex initialization error:',
                err?.message || err
            );

            this._displayErrorDialog(
                _t("初始化錯誤"),
                err?.message
                || _t("支付服務初始化失敗"),
            );

            this._enableButton();
        }
    },
});