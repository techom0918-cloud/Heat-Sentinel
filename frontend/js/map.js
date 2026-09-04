/**
 * Heat Sentinel - Leaflet GIS Map Component
 * Handles map initialization, layer rendering, transit stops visualization, and legend controls.
 */

class MapManager {
    constructor() {
        this.map = null;
        this.transitLayerGroup = L.layerGroup();
        this.cityMarkerGroup = L.layerGroup();
        this.transitStops = [];
        this.isTransitLoaded = false;
        
        // Color tokens for risk categories
        this.riskColors = {
            'LOW': '#10B981',       // Emerald Green
            'MODERATE': '#F59E0B',  // Amber Gold
            'HIGH': '#F97316',      // Orange
            'VERY_HIGH': '#EF4444', // Red
            'EXTREME': '#B91C1C',   // Dark Crimson
            'NOT_CLASSIFIED': '#6B7280'
        };
    }

    /**
     * Map a risk string to hex color.
     */
    getColor(riskTier) {
        if (!riskTier) return '#9CA3AF';
        const key = String(riskTier).trim().toUpperCase();
        return this.riskColors[key] || '#9CA3AF';
    }

    /**
     * Initialize Leaflet map instance centered on Delhi.
     */
    initMap(elementId = 'map') {
        const defaultCenter = [28.6139, 77.2090];
        const defaultZoom = 12;

        this.map = L.map(elementId, {
            center: defaultCenter,
            zoom: defaultZoom,
            zoomControl: false // Custom position added below
        });

        // Add standard zoom control on top-left
        L.control.zoom({ position: 'topleft' }).addTo(this.map);

        // Add CartoDB Positron / OSM Base Tiles
        L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/">CARTO</a>',
            subdomains: 'abcd',
            maxZoom: 19
        }).addTo(this.map);

        // Add layer groups to map
        this.transitLayerGroup.addTo(this.map);
        this.cityMarkerGroup.addTo(this.map);

        // Add map controls
        this._addLegend();
        
        // Load transit stop dataset
        this.loadTransitStops();

        return this.map;
    }

    /**
     * Load real transit stops from frontend/data/transit_stops refined.csv using PapaParse.
     */
    loadTransitStops() {
        const csvPath = 'data/transit_stops refined.csv';
        const self = this;

        if (typeof Papa === 'undefined') {
            console.error('PapaParse library is not loaded');
            return;
        }

        Papa.parse(csvPath, {
            download: true,
            header: true,
            dynamicTyping: true,
            skipEmptyLines: true,
            complete: function(results) {
                if (!results.data || !Array.isArray(results.data)) {
                    console.warn('Transit dataset returned empty or invalid records');
                    return;
                }

                // Filter for Delhi stops with valid coordinates
                self.transitStops = results.data.filter(row => 
                    row && row.city === 'Delhi' && 
                    typeof row.lat === 'number' && !isNaN(row.lat) &&
                    typeof row.lon === 'number' && !isNaN(row.lon)
                );

                self._renderTransitStops();
                self.isTransitLoaded = true;
                console.log(`[HeatSentinel GIS] Loaded ${self.transitStops.length} real Delhi transit stops`);
            },
            error: function(error) {
                console.error('[HeatSentinel GIS] Failed to parse transit dataset:', error);
            }
        });
    }

    /**
     * Render circle markers for each transit stop on the map.
     */
    _renderTransitStops() {
        this.transitLayerGroup.clearLayers();

        this.transitStops.forEach(stop => {
            const color = this.getColor(stop.thei_tier);
            const marker = L.circleMarker([stop.lat, stop.lon], {
                radius: 5,
                fillColor: color,
                color: '#FFFFFF',
                weight: 1,
                fillOpacity: 0.85
            });

            const popupHtml = `
                <div class="gis-popup">
                    <div class="gis-popup-header" style="border-bottom: 2px solid ${color}; padding-bottom: 4px; margin-bottom: 6px;">
                        <strong style="font-size: 14px; color: #1F2937;">${stop.name || 'Transit Stop'}</strong>
                    </div>
                    <div style="font-size: 12px; color: #4B5563; line-height: 1.5;">
                        <div><strong>Mode:</strong> ${stop.mode || 'N/A'}</div>
                        <div><strong>Transit Heat Exposure (THEI):</strong> ${stop.thei !== undefined ? Number(stop.thei).toFixed(1) : 'N/A'}</div>
                        <div><strong>Transit Exposure Tier:</strong> <span style="font-weight: 700; color: ${color};">${stop.thei_tier || 'N/A'}</span></div>
                        <div style="font-size: 10px; color: #9CA3AF; margin-top: 4px; font-style: italic;">Note: Transit exposure metric from GTFS dataset (not ML prediction).</div>
                    </div>
                </div>
            `;

            marker.bindPopup(popupHtml);
            this.transitLayerGroup.addLayer(marker);
        });
    }

    /**
     * Update Central City Status Marker on the map.
     */
    updateCityMarker(cityName = 'Delhi Center', riskCategory = 'UNKNOWN', heatIndexMax = null, sourceLabel = 'City Station') {
        this.cityMarkerGroup.clearLayers();

        const coords = [28.6139, 77.2090];
        const color = this.getColor(riskCategory);

        // Center pulse circle
        const cityCircle = L.circle(coords, {
            radius: 2500,
            color: color,
            fillColor: color,
            fillOpacity: 0.15,
            weight: 2,
            dashArray: '4, 6'
        });

        // Center pin marker
        const cityPin = L.circleMarker(coords, {
            radius: 9,
            fillColor: color,
            color: '#FFFFFF',
            weight: 3,
            fillOpacity: 1.0
        });

        const popupContent = `
            <div class="gis-popup">
                <strong style="font-size: 14px; color: #111827;">${cityName} Weather Station</strong><br>
                <span style="font-size: 12px; color: #6B7280;">Central Coordinates: 28.6139° N, 77.2090° E</span>
                <hr style="margin: 6px 0; border: none; border-top: 1px solid #E5E7EB;">
                <div style="font-size: 13px;">
                    <strong>Category (${sourceLabel}):</strong> <span style="color: ${color}; font-weight: 700;">${riskCategory}</span><br>
                    ${heatIndexMax ? `<strong>Max Temp / Heat Index:</strong> ${heatIndexMax} °C` : ''}
                </div>
            </div>
        `;

        cityCircle.bindPopup(popupContent);
        cityPin.bindPopup(popupContent);

        this.cityMarkerGroup.addLayer(cityCircle);
        this.cityMarkerGroup.addLayer(cityPin);
    }

    /**
     * Render risk color legend on the bottom right of the map.
     */
    _addLegend() {
        const legend = L.control({ position: 'bottomright' });

        legend.onAdd = () => {
            const div = L.DomUtil.create('div', 'leaflet-control-legend');
            div.style.backgroundColor = 'rgba(255, 255, 255, 0.95)';
            div.style.backdropFilter = 'blur(8px)';
            div.style.padding = '12px 14px';
            div.style.borderRadius = '10px';
            div.style.boxShadow = '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)';
            div.style.fontSize = '12px';
            div.style.fontFamily = 'Inter, system-ui, sans-serif';
            div.style.lineHeight = '1.6';
            div.style.maxWidth = '230px';

            div.innerHTML = `
                <div style="font-weight: 700; color: #111827; margin-bottom: 6px; border-bottom: 1px solid #E5E7EB; padding-bottom: 4px;">
                    Heat Risk Index Scale
                </div>
                <div style="display: flex; align-items: center; margin-bottom: 3px;">
                    <span style="width: 12px; height: 12px; border-radius: 3px; background: ${this.riskColors.LOW}; margin-right: 8px; display: inline-block;"></span>
                    <span>Low (&lt; 27°C)</span>
                </div>
                <div style="display: flex; align-items: center; margin-bottom: 3px;">
                    <span style="width: 12px; height: 12px; border-radius: 3px; background: ${this.riskColors.MODERATE}; margin-right: 8px; display: inline-block;"></span>
                    <span>Moderate (27–32°C)</span>
                </div>
                <div style="display: flex; align-items: center; margin-bottom: 3px;">
                    <span style="width: 12px; height: 12px; border-radius: 3px; background: ${this.riskColors.HIGH}; margin-right: 8px; display: inline-block;"></span>
                    <span>High (32–41°C)</span>
                </div>
                <div style="display: flex; align-items: center; margin-bottom: 3px;">
                    <span style="width: 12px; height: 12px; border-radius: 3px; background: ${this.riskColors.VERY_HIGH}; margin-right: 8px; display: inline-block;"></span>
                    <span>Very High / Extreme (&gt; 41°C)</span>
                </div>
                <div style="font-size: 10px; color: #6B7280; margin-top: 6px; padding-top: 4px; border-top: 1px solid #F3F4F6;">
                    Circle Markers: Delhi Transit Stop Heat Exposure (THEI Dataset)
                </div>
            `;
            return div;
        };

        legend.addTo(this.map);
    }

    /**
     * Trigger Leaflet map container resize recalculation.
     */
    invalidateSize() {
        if (this.map) {
            this.map.invalidateSize();
        }
    }
}

window.mapManager = new MapManager();
