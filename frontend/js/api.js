/**
 * Heat Sentinel - API Service Layer
 * Centralized API client for communicating with the FastAPI backend.
 */

const CONFIG = {
    API_BASE_URL: (window.HEAT_SENTINEL_CONFIG && window.HEAT_SENTINEL_CONFIG.API_BASE_URL) 
        ? window.HEAT_SENTINEL_CONFIG.API_BASE_URL 
        : 'http://127.0.0.1:8000/api/v1',
    DEFAULT_COORDS: {
        lat: 28.6139,
        lon: 77.2090,
        city: 'Delhi'
    },
    TIMEOUT_MS: 15000
};

class ApiService {
    constructor() {
        this.baseUrl = CONFIG.API_BASE_URL;
    }

    async _fetchJson(endpoint, options = {}) {
        const url = `${this.baseUrl}${endpoint}`;
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), CONFIG.TIMEOUT_MS);

        try {
            const response = await fetch(url, {
                ...options,
                signal: controller.signal,
                headers: {
                    'Accept': 'application/json',
                    ...(options.headers || {})
                }
            });
            clearTimeout(timeoutId);

            if (!response.ok) {
                let errorData = {};
                try {
                    errorData = await response.json();
                } catch (e) {
                    // Ignore body parsing failure
                }
                const errorMsg = errorData.detail || errorData.message || `HTTP ${response.status}: ${response.statusText}`;
                const err = new Error(errorMsg);
                err.status = response.status;
                err.details = errorData;
                throw err;
            }

            return await response.json();
        } catch (error) {
            clearTimeout(timeoutId);
            if (error.name === 'AbortError') {
                const timeoutErr = new Error(`Request to ${endpoint} timed out after ${CONFIG.TIMEOUT_MS / 1000}s`);
                timeoutErr.status = 504;
                throw timeoutErr;
            }
            throw error;
        }
    }

    async getHealthDetails() {
        return await this._fetchJson('/health/details');
    }

    async getModelStatus() {
        return await this._fetchJson('/risk/model');
    }

    async getCurrentWeather(lat = CONFIG.DEFAULT_COORDS.lat, lon = CONFIG.DEFAULT_COORDS.lon) {
        return await this._fetchJson(`/weather/current?lat=${lat}&lon=${lon}`);
    }

    async getWeatherForecast(lat = CONFIG.DEFAULT_COORDS.lat, lon = CONFIG.DEFAULT_COORDS.lon, days = 5) {
        return await this._fetchJson(`/weather/forecast?lat=${lat}&lon=${lon}&days=${days}`);
    }

    async getCurrentThermal(lat = CONFIG.DEFAULT_COORDS.lat, lon = CONFIG.DEFAULT_COORDS.lon) {
        return await this._fetchJson(`/thermal/current?latitude=${lat}&longitude=${lon}`);
    }

    async getRiskForecast(lat = CONFIG.DEFAULT_COORDS.lat, lon = CONFIG.DEFAULT_COORDS.lon) {
        return await this._fetchJson(`/risk/forecast?latitude=${lat}&longitude=${lon}`);
    }
}

window.apiService = new ApiService();
window.HEAT_SENTINEL_CONFIG = CONFIG;
