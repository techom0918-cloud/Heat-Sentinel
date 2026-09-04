/**
 * Heat Sentinel - Main Dashboard Application Controller
 * Manages state, API integration, UI rendering, day forecast controls, and error states.
 */

document.addEventListener('DOMContentLoaded', () => {
    class DashboardApp {
        constructor() {
            this.activeDayIndex = 0; // 0 = Today, 1 = +1, 2 = +2, 3 = +3
            this.isBackendOnline = false;
            this.isLoading = true;

            // Cached API responses
            this.state = {
                health: null,
                modelStatus: null,
                weatherCurrent: null,
                weatherForecast: null,
                thermalCurrent: null,
                riskForecast: null
            };

            this.init();
        }

        async init() {
            // Initialize Leaflet Map
            if (window.mapManager) {
                window.mapManager.initMap('map');
            }

            // Setup UI Event Listeners
            this._setupEventListeners();

            // Initial Data Load
            await this.loadAllData();
        }

        _setupEventListeners() {
            // Day selector buttons
            const dayButtons = document.querySelectorAll('.day-btn');
            dayButtons.forEach((btn, index) => {
                btn.addEventListener('click', () => {
                    this.switchDay(index);
                });
            });

            // Retry connection button
            const retryBtn = document.getElementById('retry-btn');
            if (retryBtn) {
                retryBtn.addEventListener('click', () => {
                    this.loadAllData();
                });
            }

            // Mobile drawer toggle button (if exists)
            const mobileToggleBtn = document.getElementById('mobile-toggle-btn');
            const sidebar = document.getElementById('sidebar');
            if (mobileToggleBtn && sidebar) {
                mobileToggleBtn.addEventListener('click', () => {
                    sidebar.classList.toggle('open');
                    setTimeout(() => {
                        if (window.mapManager) window.mapManager.invalidateSize();
                    }, 300);
                });
            }
        }

        /**
         * Fetch all backend endpoints concurrently.
         */
        async loadAllData() {
            this._setLoadingState(true);
            this._hideErrorBanner();

            try {
                const api = window.apiService;

                // Execute backend calls with Promise.allSettled
                const [
                    healthRes,
                    modelRes,
                    weatherCurrRes,
                    weatherFcRes,
                    thermalCurrRes,
                    riskFcRes
                ] = await Promise.allSettled([
                    api.getHealthDetails(),
                    api.getModelStatus(),
                    api.getCurrentWeather(),
                    api.getWeatherForecast(28.6139, 77.2090, 5),
                    api.getCurrentThermal(),
                    api.getRiskForecast()
                ]);

                // Evaluate health check status
                if (healthRes.status === 'fulfilled') {
                    this.state.health = healthRes.value;
                    this.isBackendOnline = true;
                } else {
                    this.isBackendOnline = false;
                }

                if (modelRes.status === 'fulfilled') this.state.modelStatus = modelRes.value;
                if (weatherCurrRes.status === 'fulfilled') this.state.weatherCurrent = weatherCurrRes.value;
                if (weatherFcRes.status === 'fulfilled') this.state.weatherForecast = weatherFcRes.value;
                if (thermalCurrRes.status === 'fulfilled') this.state.thermalCurrent = thermalCurrRes.value;
                if (riskFcRes.status === 'fulfilled') this.state.riskForecast = riskFcRes.value;

                if (!this.isBackendOnline && riskFcRes.status === 'rejected' && thermalCurrRes.status === 'rejected') {
                    this._showErrorBanner('Backend unavailable - unable to load live heat-risk data.');
                } else {
                    this._updateHeaderStatus();
                }

                // Render UI based on current active day
                this.renderUI();
            } catch (err) {
                console.error('[HeatSentinel App] Error loading data:', err);
                this.isBackendOnline = false;
                this._showErrorBanner('Backend connection failed. Displaying local offline GIS transit dataset.');
                this.renderUI();
            } finally {
                this._setLoadingState(false);
            }
        }

        /**
         * Switch active forecast day index (0 = Today, 1 = +1, 2 = +2, 3 = +3)
         */
        switchDay(dayIndex) {
            this.activeDayIndex = dayIndex;

            // Update button UI states
            const dayButtons = document.querySelectorAll('.day-btn');
            dayButtons.forEach((btn, idx) => {
                if (idx === dayIndex) {
                    btn.classList.add('active');
                } else {
                    btn.classList.remove('active');
                }
            });

            this.renderUI();
        }

        /**
         * Update all view panels based on activeDayIndex and backend state.
         */
        renderUI() {
            this._renderWeatherCard();
            this._renderThermalCard();
            this._renderMlPredictionCard();
            this._renderModelStatusBadge();
            this._updateMapCityMarker();
        }

        /**
         * Render Weather Information Card
         */
        _renderWeatherCard() {
            const tempEl = document.getElementById('val-temp');
            const humidityEl = document.getElementById('val-humidity');
            const windEl = document.getElementById('val-wind');
            const solarEl = document.getElementById('val-solar');
            const weatherDescEl = document.getElementById('weather-desc');

            if (!this.isBackendOnline) {
                if (tempEl) tempEl.textContent = '-- °C';
                if (humidityEl) humidityEl.textContent = '-- %';
                if (windEl) windEl.textContent = '-- m/s';
                if (solarEl) solarEl.textContent = '-- W/m²';
                if (weatherDescEl) weatherDescEl.textContent = 'Backend Offline';
                return;
            }

            if (this.activeDayIndex === 0 && this.state.weatherCurrent) {
                // Today: Current weather observation
                const curr = this.state.weatherCurrent.current;
                if (tempEl) tempEl.textContent = `${curr.temperature_c !== undefined ? curr.temperature_c.toFixed(1) : '--'} °C`;
                if (humidityEl) humidityEl.textContent = `${curr.relative_humidity !== undefined ? Math.round(curr.relative_humidity) : '--'} %`;
                if (windEl) windEl.textContent = `${curr.wind_speed_ms !== undefined ? curr.wind_speed_ms.toFixed(1) : '--'} m/s`;
                if (solarEl) solarEl.textContent = `${curr.solar_radiation_wm2 !== undefined ? Math.round(curr.solar_radiation_wm2) : '--'} W/m²`;
                if (weatherDescEl) weatherDescEl.textContent = `Observed at ${new Date(curr.observed_at).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}`;
            } else if (this.state.weatherForecast && this.state.weatherForecast.forecast) {
                // Forecast Days (+1, +2, +3)
                const fcList = this.state.weatherForecast.forecast;
                const fcItem = fcList[this.activeDayIndex];

                if (fcItem) {
                    if (tempEl) tempEl.textContent = `${fcItem.temperature_max_c !== undefined ? fcItem.temperature_max_c.toFixed(1) : '--'} °C (Max)`;
                    if (humidityEl) humidityEl.textContent = `${fcItem.relative_humidity_at_max_temp !== undefined ? Math.round(fcItem.relative_humidity_at_max_temp) : (fcItem.relative_humidity_mean ? Math.round(fcItem.relative_humidity_mean) : '--')} %`;
                    if (windEl) windEl.textContent = `${fcItem.wind_speed_max_ms !== undefined ? fcItem.wind_speed_max_ms.toFixed(1) : '--'} m/s (Max)`;
                    if (solarEl) solarEl.textContent = `${fcItem.solar_radiation_max_wm2 !== undefined ? Math.round(fcItem.solar_radiation_max_wm2) : '--'} W/m² (Peak)`;
                    if (weatherDescEl) weatherDescEl.textContent = `Forecast Date: ${fcItem.date}`;
                }
            }
        }

        /**
         * Render Thermal Indicators Card (Heat Index, WBGT, UTCI)
         */
        _renderThermalCard() {
            const hiEl = document.getElementById('val-hi');
            const hiCatEl = document.getElementById('cat-hi');
            const wbgtEl = document.getElementById('val-wbgt');
            const utciEl = document.getElementById('val-utci');
            const utciCatEl = document.getElementById('cat-utci');

            if (!this.isBackendOnline || !this.state.thermalCurrent) {
                if (hiEl) hiEl.textContent = '-- °C';
                if (hiCatEl) hiCatEl.textContent = 'OFFLINE';
                if (wbgtEl) wbgtEl.textContent = '-- °C';
                if (utciEl) utciEl.textContent = '-- °C';
                if (utciCatEl) utciCatEl.textContent = 'OFFLINE';
                return;
            }

            const thermal = this.state.thermalCurrent.thermal;
            if (hiEl) hiEl.textContent = `${thermal.heat_index !== null ? thermal.heat_index.toFixed(1) : '--'} °C`;
            if (hiCatEl) {
                hiCatEl.textContent = thermal.heat_index_category;
                hiCatEl.className = `category-badge cat-${thermal.heat_index_category.toLowerCase()}`;
            }

            if (wbgtEl) wbgtEl.textContent = `${thermal.wbgt !== null ? thermal.wbgt.toFixed(1) : '--'} °C`;
            if (utciEl) utciEl.textContent = `${thermal.utci !== null ? thermal.utci.toFixed(1) : 'N/A'}`;
            if (utciCatEl) {
                utciCatEl.textContent = thermal.utci_category;
                utciCatEl.className = `category-badge cat-${thermal.utci_category.toLowerCase()}`;
            }
        }

        /**
         * Render ML Prediction Information Card
         * Handles honest behavior for Today, +1/+2, and +3 Day ML Horizon.
         */
        _renderMlPredictionCard() {
            const mlContainer = document.getElementById('ml-prediction-card');
            if (!mlContainer) return;

            if (!this.isBackendOnline) {
                mlContainer.innerHTML = `
                    <div class="card-header">
                        <span class="card-icon">ML</span>
                        <h3>ML Risk Prediction</h3>
                    </div>
                    <div class="offline-placeholder" style="padding: 16px; text-align: center; color: #6B7280;">
                        <p style="margin: 0; font-size: 13px;">Backend offline - ML prediction unavailable.</p>
                    </div>
                `;
                return;
            }

            const riskFc = this.state.riskForecast;

            if (this.activeDayIndex === 3) {
                // +3 Days: Real ML Prediction Available!
                if (riskFc) {
                    const predictedCat = riskFc.predicted_category || 'UNKNOWN';
                    const confidence = riskFc.confidence !== null && riskFc.confidence !== undefined 
                        ? `${(riskFc.confidence * 100).toFixed(1)}%` 
                        : 'N/A';
                    const currentCat = riskFc.current_category || 'N/A';
                    const classProbs = riskFc.class_probabilities || {};

                    // Generate probability bar distribution HTML
                    let probBarsHtml = '';
                    const riskLevels = ['LOW', 'MODERATE', 'HIGH', 'VERY_HIGH', 'EXTREME'];
                    riskLevels.forEach(lvl => {
                        const prob = classProbs[lvl] || 0;
                        const pct = (prob * 100).toFixed(0);
                        probBarsHtml += `
                            <div style="margin-bottom: 6px;">
                                <div style="display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 2px;">
                                    <span style="font-weight: 600; color: #4B5563;">${lvl}</span>
                                    <span style="color: #6B7280;">${pct}%</span>
                                </div>
                                <div style="height: 6px; background: #E5E7EB; border-radius: 3px; overflow: hidden;">
                                    <div style="width: ${pct}%; height: 100%; background: ${window.mapManager ? window.mapManager.getColor(lvl) : '#3B82F6'}; transition: width 0.4s ease;"></div>
                                </div>
                            </div>
                        `;
                    });

                    mlContainer.innerHTML = `
                        <div class="card-header" style="display: flex; justify-content: space-between; align-items: center;">
                            <div style="display: flex; align-items: center; gap: 8px;">
                                <span class="card-icon">ML</span>
                                <h3 style="margin: 0;">ML 3-Day Hazard Forecast</h3>
                            </div>
                            <span class="category-badge cat-${predictedCat.toLowerCase()}" style="font-size: 13px; padding: 4px 10px;">${predictedCat}</span>
                        </div>
                        <div class="card-body" style="font-size: 13px; color: #374151;">
                            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 14px; background: #F9FAFB; padding: 10px; border-radius: 8px;">
                                <div>
                                    <div style="font-size: 11px; color: #6B7280;">Forecast Lead</div>
                                    <div style="font-weight: 700; color: #111827;">+3 Days Horizon</div>
                                </div>
                                <div>
                                    <div style="font-size: 11px; color: #6B7280;">Model Confidence</div>
                                    <div style="font-weight: 700; color: #059669;">${confidence}</div>
                                </div>
                                <div>
                                    <div style="font-size: 11px; color: #6B7280;">Based On</div>
                                    <div style="font-weight: 600;">${riskFc.based_on || 'Today'}</div>
                                </div>
                                <div>
                                    <div style="font-size: 11px; color: #6B7280;">Issued For</div>
                                    <div style="font-weight: 600;">${riskFc.issued_for || 'T+3'}</div>
                                </div>
                            </div>

                            <div style="margin-bottom: 12px;">
                                <div style="font-size: 12px; font-weight: 600; color: #374151; margin-bottom: 6px;">Class Probability Distribution</div>
                                ${probBarsHtml}
                            </div>

                            <div style="font-size: 11px; color: #6B7280; border-top: 1px solid #F3F4F6; padding-top: 8px; margin-top: 8px;">
                                <strong>Persistence Baseline (Today):</strong> ${currentCat} (${riskFc.current_heat_index_max} °C peak)
                            </div>
                        </div>
                    `;
                } else {
                    mlContainer.innerHTML = `
                        <div class="card-header"><span class="card-icon">ML</span><h3>ML Risk Prediction</h3></div>
                        <p style="padding: 12px; font-size: 13px; color: #EF4444;">ML forecast artifact unavailable (503). Run <code>ml/heat_pipeline.py</code> to train.</p>
                    `;
                }
            } else if (this.activeDayIndex === 0) {
                // Today (Day 0)
                const currentCat = riskFc ? riskFc.current_category : (this.state.thermalCurrent ? this.state.thermalCurrent.thermal.heat_index_category : 'UNKNOWN');
                mlContainer.innerHTML = `
                    <div class="card-header" style="display: flex; justify-content: space-between; align-items: center;">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <span class="card-icon">STAT</span>
                            <h3 style="margin: 0;">Today's Heat Risk Status</h3>
                        </div>
                        <span class="category-badge cat-${currentCat.toLowerCase()}" style="font-size: 13px; padding: 4px 10px;">${currentCat}</span>
                    </div>
                    <div class="card-body" style="font-size: 13px; color: #374151; padding-top: 6px;">
                        <p style="margin: 0 0 10px 0; line-height: 1.5; color: #4B5563;">
                            Currently observing <strong>${currentCat}</strong> thermal stress based on real-time weather stations in Delhi.
                        </p>
                        <div style="background: #EFF6FF; border-left: 3px solid #3B82F6; padding: 8px 12px; border-radius: 4px; font-size: 12px; color: #1E40AF;">
                            Notice: Select the <strong>+3</strong> button to inspect the AI ML 3-day lead hazard forecast.
                        </div>
                    </div>
                `;
            } else {
                // +1 or +2 Days
                mlContainer.innerHTML = `
                    <div class="card-header">
                        <span class="card-icon">FCST</span>
                        <h3>Weather Forecast (+${this.activeDayIndex} Day)</h3>
                    </div>
                    <div class="card-body" style="font-size: 13px; color: #374151;">
                        <p style="margin: 0 0 10px 0; color: #4B5563;">
                            Showing weather & thermal condition forecasts for <strong>+${this.activeDayIndex} day</strong>.
                        </p>
                        <div style="background: #FFFBEB; border-left: 3px solid #F59E0B; padding: 10px 12px; border-radius: 4px; font-size: 12px; color: #92400E;">
                            <strong>ML Horizon Note:</strong> The ML model is specifically trained for a <strong>+3 day lead forecast</strong>. Select the <strong>+3</strong> tab to view the ML hazard model prediction.
                        </div>
                    </div>
                `;
            }
        }

        /**
         * Render Model Status Badge in Header
         */
        _renderModelStatusBadge() {
            const statusBadge = document.getElementById('model-status-badge');
            if (!statusBadge) return;

            if (!this.isBackendOnline) {
                statusBadge.innerHTML = `<span class="status-dot offline"></span> API Offline`;
                statusBadge.className = 'badge badge-offline';
                return;
            }

            const modelStat = this.state.modelStatus;
            if (modelStat && modelStat.available) {
                const info = modelStat.model_info || {};
                const csi = info.test_metrics && info.test_metrics.CSI !== undefined 
                    ? ` (CSI: ${info.test_metrics.CSI})` 
                    : '';
                statusBadge.innerHTML = `<span class="status-dot online"></span> ${info.type || 'ML Model'} Ready${csi}`;
                statusBadge.className = 'badge badge-online';
            } else {
                statusBadge.innerHTML = `<span class="status-dot warning"></span> ML Model Unloaded`;
                statusBadge.className = 'badge badge-warning';
            }
        }

        /**
         * Update City Marker on GIS Map
         */
        _updateMapCityMarker() {
            if (!window.mapManager) return;

            let cat = 'LOW';
            let hiPeak = null;
            let sourceLabel = 'Observed Station';

            if (this.activeDayIndex === 3 && this.state.riskForecast) {
                cat = this.state.riskForecast.predicted_category;
                sourceLabel = 'ML Hazard Forecast (+3d)';
            } else if (this.activeDayIndex === 0 && this.state.thermalCurrent) {
                cat = this.state.thermalCurrent.thermal.heat_index_category;
                hiPeak = this.state.thermalCurrent.thermal.heat_index;
                sourceLabel = 'Observed Today';
            } else if (this.state.weatherForecast && this.state.weatherForecast.forecast) {
                const fcItem = this.state.weatherForecast.forecast[this.activeDayIndex];
                if (fcItem && fcItem.temperature_max_c) {
                    const temp = fcItem.temperature_max_c;
                    if (temp >= 41) cat = 'VERY_HIGH';
                    else if (temp >= 32) cat = 'HIGH';
                    else if (temp >= 27) cat = 'MODERATE';
                    else cat = 'LOW';
                    hiPeak = temp;
                    sourceLabel = `Weather Forecast (+${this.activeDayIndex}d)`;
                }
            }

            window.mapManager.updateCityMarker('Delhi Central Station', cat, hiPeak ? hiPeak.toFixed(1) : null, sourceLabel);
        }

        _setLoadingState(loading) {
            this.isLoading = loading;
            const loader = document.getElementById('loading-overlay');
            if (loader) {
                loader.style.display = loading ? 'flex' : 'none';
            }
        }

        _updateHeaderStatus() {
            const connBadge = document.getElementById('connection-status');
            if (connBadge) {
                if (this.isBackendOnline) {
                    connBadge.innerHTML = `<span class="status-dot online"></span> Backend Connected`;
                    connBadge.className = 'badge badge-online';
                } else {
                    connBadge.innerHTML = `<span class="status-dot offline"></span> Backend Disconnected`;
                    connBadge.className = 'badge badge-offline';
                }
            }
        }

        _showErrorBanner(message) {
            const banner = document.getElementById('error-banner');
            const msgEl = document.getElementById('error-message');
            if (banner && msgEl) {
                msgEl.textContent = message;
                banner.style.display = 'flex';
            }
        }

        _hideErrorBanner() {
            const banner = document.getElementById('error-banner');
            if (banner) {
                banner.style.display = 'none';
            }
        }
    }

    // Launch App
    window.app = new DashboardApp();
});
