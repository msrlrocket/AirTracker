/**
 * AirTracker Web Display - Touch-Optimized JavaScript
 *
 * Handles real-time data updates, navigation, and touch interactions
 * for the Pi Zero touchscreen display.
 */

class AirTrackerApp {
    constructor() {
        this.socket = null;
        this.currentView = window.AIRTRACKER_CONFIG?.currentView || 'nearest';
        this.data = {
            nearest: null,
            nearest_commercial: null,
            nearest_military: null,
            planes: [],
            last_updated: null
        };
        this.connectionStatus = 'disconnected';

        this.init();
    }

    init() {
        // Initialize Socket.IO connection
        this.initSocket();

        // Initialize navigation
        this.initNavigation();

        // Initialize touch handlers
        this.initTouchHandlers();

        // Initialize shadowboxes
        this.initShadowboxes();

        // Set initial view
        this.showView(this.currentView);

        console.log('AirTracker Web Display initialized');
    }

    initSocket() {
        // Connect to WebSocket
        this.socket = io();

        this.socket.on('connect', () => {
            console.log('Connected to server');
            this.updateConnectionStatus('connected');
        });

        this.socket.on('disconnect', () => {
            console.log('Disconnected from server');
            this.updateConnectionStatus('disconnected');
        });

        this.socket.on('initial_data', (data) => {
            console.log('Received initial data:', data);
            this.updateAllData(data);
        });

        this.socket.on('aircraft_update', (update) => {
            console.log(`Aircraft update: ${update.topic}`);
            this.handleAircraftUpdate(update);
        });

        this.socket.on('mqtt_status', (status) => {
            console.log('MQTT status update:', status.status);
            this.updateMqttStatus(status);
        });

        this.socket.on('connect_error', (error) => {
            console.error('Connection error:', error);
            this.updateConnectionStatus('error');
        });
    }

    initNavigation() {
        const menuToggle = document.getElementById('menuToggle');
        const navMenu = document.getElementById('navMenu');
        const navOverlay = document.getElementById('navOverlay');
        const navClose = document.getElementById('navClose');
        const navLinks = document.querySelectorAll('.nav-link');

        // Menu toggle handlers
        menuToggle?.addEventListener('click', () => this.toggleMenu());
        navClose?.addEventListener('click', () => this.closeMenu());
        navOverlay?.addEventListener('click', () => this.closeMenu());

        // Navigation link handlers
        navLinks.forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                const view = link.dataset.view;
                if (view) {
                    this.navigateToView(view);
                }
            });
        });

        // Handle browser back/forward
        window.addEventListener('popstate', (e) => {
            const view = e.state?.view || 'nearest';
            this.showView(view, false);
        });
    }

    initTouchHandlers() {
        // Add touch feedback to clickable elements
        const clickables = document.querySelectorAll('button, .nav-link, .clickable');

        clickables.forEach(element => {
            // Touch start - add active state
            element.addEventListener('touchstart', (e) => {
                element.classList.add('touching');
            }, { passive: true });

            // Touch end - remove active state
            element.addEventListener('touchend', (e) => {
                setTimeout(() => {
                    element.classList.remove('touching');
                }, 150);
            }, { passive: true });

            // Touch cancel - remove active state
            element.addEventListener('touchcancel', (e) => {
                element.classList.remove('touching');
            }, { passive: true });
        });

        // Prevent iOS bounce scroll
        document.addEventListener('touchmove', (e) => {
            if (e.target.closest('.nav-menu')) {
                return; // Allow scrolling in menu
            }
            e.preventDefault();
        }, { passive: false });
    }

    toggleMenu() {
        const menuToggle = document.getElementById('menuToggle');
        const navMenu = document.getElementById('navMenu');
        const navOverlay = document.getElementById('navOverlay');

        const isActive = navMenu?.classList.contains('active');

        if (isActive) {
            this.closeMenu();
        } else {
            menuToggle?.classList.add('active');
            navMenu?.classList.add('active');
            navOverlay?.classList.add('active');
        }
    }

    closeMenu() {
        const menuToggle = document.getElementById('menuToggle');
        const navMenu = document.getElementById('navMenu');
        const navOverlay = document.getElementById('navOverlay');

        menuToggle?.classList.remove('active');
        navMenu?.classList.remove('active');
        navOverlay?.classList.remove('active');
    }

    navigateToView(view) {
        // Update URL without page reload
        const url = view === 'nearest' ? '/' : `/${view}`;
        history.pushState({ view }, '', url);

        // Show the view
        this.showView(view);

        // Close menu
        this.closeMenu();
    }

    showView(view, updateNav = true) {
        this.currentView = view;

        // Update view visibility
        document.querySelectorAll('.view').forEach(v => {
            v.classList.remove('active');
        });
        document.getElementById(`${view}View`)?.classList.add('active');

        // Update page title
        const titles = {
            nearest: 'Nearest Aircraft',
            military: 'Military Aircraft',
            radar: 'Radar View',
            planes: 'All Aircraft'
        };

        const titleElement = document.querySelector('.title-text');
        if (titleElement) {
            titleElement.textContent = titles[view] || 'AirTracker';
        }

        // Update navigation active state
        if (updateNav) {
            document.querySelectorAll('.nav-link').forEach(link => {
                link.classList.remove('active');
                if (link.dataset.view === view) {
                    link.classList.add('active');
                }
            });
        }

        // Refresh view data
        this.updateViewData(view);
    }

    updateAllData(data) {
        this.data = { ...this.data, ...data };
        this.updateViewData(this.currentView);
        this.updateFooter();
        this.updateMqttStatus({ status: data.mqtt_status });
    }

    handleAircraftUpdate(update) {
        const { topic, data, timestamp } = update;

        // Update data store
        if (topic === 'nearest') {
            this.data.nearest = data;
        } else if (topic === 'nearest_commercial') {
            this.data.nearest_commercial = data;
        } else if (topic === 'nearest_military') {
            this.data.nearest_military = data;
        } else if (topic === 'planes') {
            this.data.planes = Array.isArray(data) ? data : [];
        }

        this.data.last_updated = timestamp;

        // Update current view if relevant
        this.updateViewData(this.currentView);
        this.updateFooter();
    }

    updateViewData(view) {
        switch (view) {
            case 'nearest':
                this.updateNearestView();
                break;
            case 'commercial':
                this.updateCommercialView();
                break;
            case 'military':
                this.updateMilitaryView();
                break;
            case 'radar':
                // Placeholder - no data updates needed
                break;
            case 'planes':
                this.updatePlanesView();
                break;
        }
    }

    updateNearestView() {
        const loadingState = document.querySelector('#nearestCard .loading-state');
        const aircraftDisplay = document.querySelector('#nearestCard .aircraft-display');
        const aircraft = this.data.nearest;

        console.log('updateNearestView called, aircraft:', aircraft);

        if (!aircraft) {
            console.log('No aircraft data, showing loading state');
            if (loadingState) loadingState.style.display = 'flex';
            if (aircraftDisplay) aircraftDisplay.style.display = 'none';
            return;
        }

        // Hide loading and show aircraft display
        console.log('Aircraft data found, showing aircraft display');
        if (loadingState) loadingState.style.display = 'none';
        if (aircraftDisplay) {
            aircraftDisplay.style.display = 'block';
            this.populateAircraftDisplay(aircraft);
        }
    }

    updateCommercialView() {
        const loadingState = document.querySelector('#commercialCard .loading-state');
        const aircraftDisplay = document.querySelector('#commercialCard .aircraft-display');
        const aircraft = this.data.nearest_commercial;

        console.log('updateCommercialView called, aircraft:', aircraft);

        if (!aircraft) {
            console.log('No commercial aircraft data, showing loading state');
            if (loadingState) loadingState.style.display = 'flex';
            if (aircraftDisplay) aircraftDisplay.style.display = 'none';
            return;
        }

        console.log('Commercial aircraft found, populating display');
        if (loadingState) loadingState.style.display = 'none';
        if (aircraftDisplay) aircraftDisplay.style.display = 'block';

        this.populateCommercialAircraftDisplay(aircraft);
    }

    updateMilitaryView() {
        const loadingState = document.querySelector('#militaryCard .loading-state');
        const aircraftDisplay = document.getElementById('militaryAircraftDisplay');
        const aircraft = this.data.nearest_military;

        if (!loadingState || !aircraftDisplay) return;

        if (!aircraft) {
            loadingState.style.display = 'flex';
            aircraftDisplay.style.display = 'none';
            return;
        }

        if (loadingState) loadingState.style.display = 'none';
        if (aircraftDisplay) aircraftDisplay.style.display = 'block';

        this.populateMilitaryAircraftDisplay(aircraft);
    }

    updatePlanesView() {
        const container = document.getElementById('planesList');
        const planes = this.data.planes || [];

        if (!container) return;

        if (planes.length === 0) {
            container.innerHTML = `
                <div class="loading-state">
                    <div class="loading-spinner"></div>
                    <p>Loading aircraft list...</p>
                </div>
            `;
            return;
        }

        const planesHtml = planes.map(plane => this.renderPlaneItem(plane)).join('');
        container.innerHTML = planesHtml;
    }

    populateAircraftDisplay(aircraft) {
        // Helper function to safely set element content
        const setElement = (id, content, defaultValue = '-') => {
            const element = document.getElementById(id);
            if (element) {
                element.textContent = content || defaultValue;
            }
        };

        const setElementSrc = (id, src) => {
            const element = document.getElementById(id);
            if (element && src) {
                element.src = src;
                element.style.display = 'block';
            } else if (element) {
                element.style.display = 'none';
            }
        };

        // Header information
        setElement('callsign', aircraft.callsign);
        setElement('airlineName', aircraft.lookups?.airline?.name);
        setElement('distance', `${aircraft.distance_nm?.toFixed(1) || '-'} nm`);
        setElement('bearing', `${aircraft.bearing_deg?.toFixed(0) || '-'}°`);

        // Images
        setElementSrc('airlineLogo', aircraft.airline_logo_url);
        setElementSrc('countryFlag', aircraft.country_flag_url);
        setElementSrc('aircraftImage', aircraft.media?.plane_image_zipline_original || aircraft.media?.plane_image);

        // Aircraft type
        setElement('aircraftType', aircraft.lookups?.aircraft?.name || aircraft.aircraft_type);

        // Route information - show if we have origin or destination info
        const hasOrigin = aircraft.lookups?.origin_airport || aircraft.origin_iata;
        const hasDestination = aircraft.lookups?.destination_airport || aircraft.destination_iata;

        if (hasOrigin || hasDestination) {
            const routeSection = document.querySelector('.route-section');
            if (routeSection) routeSection.style.display = 'block';

            // Origin
            if (hasOrigin) {
                setElement('originCode', aircraft.lookups?.origin_airport?.iata || aircraft.origin_iata || '-');
                setElement('originName', aircraft.lookups?.origin_airport?.name || 'Origin');
            } else {
                setElement('originCode', '-');
                setElement('originName', 'Unknown');
            }

            // Destination
            if (hasDestination) {
                setElement('destCode', aircraft.lookups?.destination_airport?.iata || aircraft.destination_iata || '-');
                setElement('destName', aircraft.lookups?.destination_airport?.name || 'Destination');
            } else {
                setElement('destCode', '-');
                setElement('destName', 'Private Flight');
            }

            // Route progress - only show meaningful progress if we have both origin and destination
            if (hasOrigin && hasDestination && aircraft.remaining_nm && aircraft.eta_min) {
                setElement('routeEta', `ETA: ${Math.round(aircraft.eta_min)} min`);
                setElement('routeRemaining', `${aircraft.remaining_nm.toFixed(0)} nm remaining`);

                // Calculate progress percentage
                const totalDistance = aircraft.remaining_nm + (aircraft.distance_nm || 0);
                const progressPercent = totalDistance > 0 ? ((totalDistance - aircraft.remaining_nm) / totalDistance * 100) : 0;
                const progressBar = document.getElementById('routeProgressBar');
                if (progressBar) {
                    progressBar.style.width = `${Math.max(5, progressPercent)}%`;
                }
            } else {
                // For private flights or incomplete route info, show simplified display
                setElement('routeEta', hasOrigin ? 'Private Flight' : 'Unknown Route');
                setElement('routeRemaining', '');
                const progressBar = document.getElementById('routeProgressBar');
                if (progressBar) {
                    progressBar.style.width = '0%';
                }
            }
        } else {
            // Hide route section if no route data at all
            const routeSection = document.querySelector('.route-section');
            if (routeSection) routeSection.style.display = 'none';
        }

        // Live data tiles
        setElement('altitude', aircraft.altitude_ft?.toLocaleString() || '-');
        setElement('speed', aircraft.ground_speed_kt || aircraft.speed || '-');
        setElement('verticalRate', aircraft.vertical_rate_fpm ?
            (aircraft.vertical_rate_fpm > 0 ? `+${aircraft.vertical_rate_fpm}` : aircraft.vertical_rate_fpm) : '-');
        setElement('track', aircraft.track_deg?.toFixed(0) || '-');

        // Details section
        setElement('registration', aircraft.registration);
        setElement('passengers', aircraft.souls_on_board_max_text || aircraft.souls_on_board_max || '-');
        setElement('squawk', aircraft.squawk);

        // Add click handlers for shadowboxes
        const aircraftImage = document.getElementById('aircraftImage');
        if (aircraftImage) {
            aircraftImage.style.cursor = 'pointer';
            aircraftImage.onclick = () => this.openImageGallery(aircraft);
        }

        const routeDisplay = document.querySelector('.route-display');
        if (routeDisplay) {
            routeDisplay.style.cursor = 'pointer';
            routeDisplay.onclick = () => this.openFlightHistory(aircraft);
        }
    }

    populateCommercialAircraftDisplay(aircraft) {
        // Helper function to safely set element content
        const setElement = (id, content, defaultValue = '-') => {
            const element = document.getElementById(id);
            if (element) {
                element.textContent = content || defaultValue;
            }
        };

        const setElementSrc = (id, src) => {
            const element = document.getElementById(id);
            if (element && src) {
                element.src = src;
                element.style.display = 'block';
            } else if (element) {
                element.style.display = 'none';
            }
        };

        // Header information
        setElement('commercialCallsign', aircraft.callsign);
        setElement('commercialAirlineName', aircraft.lookups?.airline?.name);
        setElement('commercialDistance', `${aircraft.distance_nm?.toFixed(1) || '-'} nm`);
        setElement('commercialBearing', `${aircraft.bearing_deg?.toFixed(0) || '-'}°`);

        // Images
        setElementSrc('commercialAirlineLogo', aircraft.airline_logo_url);
        setElementSrc('commercialCountryFlag', aircraft.country_flag_url);
        setElementSrc('commercialAircraftImage', aircraft.media?.plane_image_zipline_original || aircraft.media?.plane_image);

        // Aircraft type
        setElement('commercialAircraftType', aircraft.lookups?.aircraft?.name || aircraft.aircraft_type);

        // Route information - show if we have origin or destination info
        const hasOrigin = aircraft.lookups?.origin_airport || aircraft.origin_iata;
        const hasDestination = aircraft.lookups?.destination_airport || aircraft.destination_iata;

        if (hasOrigin || hasDestination) {
            const routeSection = document.querySelector('#commercialView .route-section');
            if (routeSection) routeSection.style.display = 'block';

            // Origin
            if (hasOrigin) {
                setElement('commercialOriginCode', aircraft.lookups?.origin_airport?.iata || aircraft.origin_iata || '-');
                setElement('commercialOriginName', aircraft.lookups?.origin_airport?.name || 'Origin');
            } else {
                setElement('commercialOriginCode', '-');
                setElement('commercialOriginName', 'Unknown');
            }

            // Destination
            if (hasDestination) {
                setElement('commercialDestCode', aircraft.lookups?.destination_airport?.iata || aircraft.destination_iata || '-');
                setElement('commercialDestName', aircraft.lookups?.destination_airport?.name || 'Destination');
            } else {
                setElement('commercialDestCode', '-');
                setElement('commercialDestName', 'Private Flight');
            }

            // Route progress - only show meaningful progress if we have both origin and destination
            if (hasOrigin && hasDestination && aircraft.remaining_nm && aircraft.eta_min) {
                setElement('commercialRouteEta', `ETA: ${Math.round(aircraft.eta_min)} min`);
                setElement('commercialRouteRemaining', `${aircraft.remaining_nm.toFixed(0)} nm remaining`);

                // Calculate progress percentage
                const totalDistance = aircraft.remaining_nm + (aircraft.distance_nm || 0);
                const progressPercent = totalDistance > 0 ? ((totalDistance - aircraft.remaining_nm) / totalDistance * 100) : 0;
                const progressBar = document.getElementById('commercialRouteProgressBar');
                if (progressBar) {
                    progressBar.style.width = `${Math.max(5, progressPercent)}%`;
                }
            } else {
                // For private flights or incomplete route info, show simplified display
                setElement('commercialRouteEta', hasOrigin ? 'Private Flight' : 'Unknown Route');
                setElement('commercialRouteRemaining', '');
                const progressBar = document.getElementById('commercialRouteProgressBar');
                if (progressBar) {
                    progressBar.style.width = '0%';
                }
            }
        } else {
            // Hide route section if no route data at all
            const routeSection = document.querySelector('#commercialView .route-section');
            if (routeSection) routeSection.style.display = 'none';
        }

        // Live data tiles
        setElement('commercialAltitude', aircraft.altitude_ft?.toLocaleString() || '-');
        setElement('commercialSpeed', aircraft.ground_speed_kt || aircraft.speed || '-');
        setElement('commercialVerticalRate', aircraft.vertical_rate_fpm ?
            (aircraft.vertical_rate_fpm > 0 ? `+${aircraft.vertical_rate_fpm}` : aircraft.vertical_rate_fpm) : '-');
        setElement('commercialTrack', aircraft.track_deg?.toFixed(0) || '-');

        // Details section
        setElement('commercialRegistration', aircraft.registration);
        setElement('commercialPassengers', aircraft.souls_on_board_max_text || aircraft.souls_on_board_max || '-');
        setElement('commercialSquawk', aircraft.squawk);

        // Add click handlers for shadowboxes
        const aircraftImage = document.getElementById('commercialAircraftImage');
        if (aircraftImage) {
            aircraftImage.style.cursor = 'pointer';
            aircraftImage.onclick = () => this.openImageGallery(aircraft);
        }

        const routeDisplay = document.querySelector('#commercialView .route-display');
        if (routeDisplay) {
            routeDisplay.style.cursor = 'pointer';
            routeDisplay.onclick = () => this.openFlightHistory(aircraft);
        }
    }

    populateMilitaryAircraftDisplay(aircraft) {
        // Helper function to safely set element content
        const setElement = (id, content, defaultValue = '-') => {
            const element = document.getElementById(id);
            if (element) {
                element.textContent = content || defaultValue;
            }
        };

        const setElementSrc = (id, src) => {
            const element = document.getElementById(id);
            if (element && src) {
                element.src = src;
                element.style.display = 'block';
            } else if (element) {
                element.style.display = 'none';
            }
        };

        // Header information
        setElement('militaryCallsign', aircraft.callsign);
        setElement('militaryAirlineName', aircraft.lookups?.airline?.name || 'Military Aircraft');
        setElement('militaryDistance', `${aircraft.distance_nm?.toFixed(1) || '-'} nm`);
        setElement('militaryBearing', `${aircraft.bearing_deg?.toFixed(0) || '-'}°`);

        // Images
        setElementSrc('militaryAirlineLogo', aircraft.airline_logo_url);
        setElementSrc('militaryCountryFlag', aircraft.country_flag_url);
        setElementSrc('militaryAircraftImage', aircraft.media?.plane_image_zipline_original || aircraft.media?.plane_image || aircraft.primary_image_url);

        // Aircraft type
        setElement('militaryAircraftType', aircraft.lookups?.aircraft?.name || aircraft.aircraft_type);

        // Route information - show if we have origin or destination info
        const hasOrigin = aircraft.lookups?.origin_airport || aircraft.origin_iata;
        const hasDestination = aircraft.lookups?.destination_airport || aircraft.destination_iata;

        if (hasOrigin || hasDestination) {
            const routeSection = document.querySelector('#militaryView .route-section');
            if (routeSection) routeSection.style.display = 'block';

            // Origin
            if (hasOrigin) {
                setElement('militaryOriginCode', aircraft.lookups?.origin_airport?.iata || aircraft.origin_iata || '-');
                setElement('militaryOriginName', aircraft.lookups?.origin_airport?.name || 'Origin');
            } else {
                setElement('militaryOriginCode', '-');
                setElement('militaryOriginName', 'Unknown');
            }

            // Destination
            if (hasDestination) {
                setElement('militaryDestCode', aircraft.lookups?.destination_airport?.iata || aircraft.destination_iata || '-');
                setElement('militaryDestName', aircraft.lookups?.destination_airport?.name || 'Destination');
            } else {
                setElement('militaryDestCode', '-');
                setElement('militaryDestName', 'Classified');
            }

            // Route progress - military flights typically don't show ETA/progress for security
            setElement('militaryRouteEta', 'Military Operation');
            setElement('militaryRouteRemaining', '');
            const progressBar = document.getElementById('militaryRouteProgressBar');
            if (progressBar) {
                progressBar.style.width = '0%';
            }
        } else {
            // Hide route section if no route data at all
            const routeSection = document.querySelector('#militaryView .route-section');
            if (routeSection) routeSection.style.display = 'none';
        }

        // Live data tiles
        setElement('militaryAltitude', aircraft.altitude_ft?.toLocaleString() || '-');
        setElement('militarySpeed', aircraft.ground_speed_kt || aircraft.speed || '-');
        setElement('militaryVerticalRate', aircraft.vertical_rate_fpm ?
            (aircraft.vertical_rate_fpm > 0 ? `+${aircraft.vertical_rate_fpm}` : aircraft.vertical_rate_fpm) : '-');
        setElement('militaryTrack', aircraft.track_deg?.toFixed(0) || '-');

        // Details section
        setElement('militaryRegistration', aircraft.registration);
        setElement('militaryPassengers', aircraft.souls_on_board_max_text || aircraft.souls_on_board_max || 'N/A');
        setElement('militarySquawk', aircraft.squawk);

        // Add click handlers for shadowboxes
        const aircraftImage = document.getElementById('militaryAircraftImage');
        if (aircraftImage) {
            aircraftImage.style.cursor = 'pointer';
            aircraftImage.onclick = () => this.openImageGallery(aircraft);
        }

        const routeDisplay = document.querySelector('#militaryView .route-display');
        if (routeDisplay) {
            routeDisplay.style.cursor = 'pointer';
            routeDisplay.onclick = () => this.openFlightHistory(aircraft);
        }
    }

    renderPlaneItem(plane) {
        const distance = plane.distance_nm?.toFixed(1) || 'N/A';
        const altitude = plane.altitude ? `${plane.altitude} ft` : 'N/A';
        const speed = plane.speed ? `${plane.speed} kt` : 'N/A';

        return `
            <div class="plane-item">
                <div class="plane-header">
                    <div class="plane-id">${plane.flight || plane.icao24 || 'Unknown'}</div>
                    <div class="plane-distance">${distance} nm</div>
                </div>
                <div class="plane-details">
                    <span>${plane.aircraft_type || 'Unknown'}</span>
                    <span>${altitude}</span>
                    <span>${speed}</span>
                </div>
            </div>
        `;
    }

    updateConnectionStatus(status) {
        this.connectionStatus = status;
        const statusElement = document.getElementById('connectionStatus');
        const statusText = statusElement?.querySelector('.status-text');

        if (!statusElement || !statusText) return;

        statusElement.className = 'status-indicator';

        switch (status) {
            case 'connected':
                statusElement.classList.add('connected');
                statusText.textContent = 'Connected';
                break;
            case 'disconnected':
                statusText.textContent = 'Disconnected';
                break;
            case 'error':
                statusElement.classList.add('error');
                statusText.textContent = 'Connection Error';
                break;
            default:
                statusText.textContent = 'Connecting...';
        }
    }

    updateMqttStatus(status) {
        // Update connection status based on MQTT status
        if (status.status === 'connected') {
            this.updateConnectionStatus('connected');
        } else if (status.status === 'error') {
            this.updateConnectionStatus('error');
        } else {
            this.updateConnectionStatus('disconnected');
        }
    }


    initShadowboxes() {
        // Close buttons
        document.getElementById('imageCloseBtn')?.addEventListener('click', () => this.closeShadowbox('imageShadowbox'));
        document.getElementById('historyCloseBtn')?.addEventListener('click', () => this.closeShadowbox('historyShadowbox'));

        // Close on overlay click
        document.getElementById('imageShadowbox')?.addEventListener('click', (e) => {
            if (e.target.id === 'imageShadowbox') this.closeShadowbox('imageShadowbox');
        });
        document.getElementById('historyShadowbox')?.addEventListener('click', (e) => {
            if (e.target.id === 'historyShadowbox') this.closeShadowbox('historyShadowbox');
        });

        // Close on escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.closeShadowbox('imageShadowbox');
                this.closeShadowbox('historyShadowbox');
            }
        });
    }

    openImageGallery(aircraft) {
        const gallery = document.getElementById('imageGallery');
        if (!gallery) return;

        // Collect all images
        const images = [];

        // Main aircraft image
        if (aircraft.media?.plane_image_zipline_original || aircraft.media?.plane_image || aircraft.primary_image_url) {
            images.push(aircraft.media.plane_image_zipline_original || aircraft.media.plane_image || aircraft.primary_image_url);
        }

        // Additional images from thumbnails or other media sources
        if (aircraft.media?.thumbnails) {
            aircraft.media.thumbnails.forEach(thumb => {
                if (thumb && thumb !== images[0]) { // Avoid duplicates
                    images.push(thumb);
                }
            });
        }

        if (aircraft.media?.additional_images) {
            aircraft.media.additional_images.forEach(img => {
                if (img && !images.includes(img)) {
                    images.push(img);
                }
            });
        }

        // Add images from enriched data (for military aircraft)
        if (aircraft.images && Array.isArray(aircraft.images)) {
            aircraft.images.forEach(imageObj => {
                const imageUrl = imageObj.zipline_url || imageObj.original_url;
                if (imageUrl && !images.includes(imageUrl)) {
                    images.push(imageUrl);
                }
            });
        }

        if (images.length === 0) {
            gallery.innerHTML = '<div class="no-history">No additional images available</div>';
        } else {
            gallery.innerHTML = images.map(img =>
                `<img src="${img}" alt="Aircraft" class="gallery-image" loading="lazy">`
            ).join('');
        }

        this.showShadowbox('imageShadowbox');
    }

    openFlightHistory(aircraft) {
        const historyContainer = document.getElementById('flightHistory');
        if (!historyContainer) return;

        const history = aircraft.history || aircraft.flight_history || aircraft.lookups?.flight_history || [];

        if (history.length === 0) {
            // Determine aircraft type for appropriate message
            const isMilitary = aircraft.is_military === true || aircraft.classification === 'Military';
            const isPrivate = !aircraft.lookups?.airline?.name && !aircraft.callsign?.match(/^[A-Z]{2,3}\d+/);

            let message = 'No flight history available';
            if (isMilitary) {
                message = 'Military Flight - No History';
            } else if (isPrivate) {
                message = 'Private Flight - No History';
            }

            historyContainer.innerHTML = `<div class="no-history">${message}</div>`;
        } else {
            historyContainer.innerHTML = history.map(flight => `
                <div class="history-item">
                    <div class="history-route">
                        <strong>${flight.flight || '-'}</strong> - ${flight.origin || '-'} → ${flight.destination || '-'}
                    </div>
                    <div class="history-details">
                        <span>Date: ${flight.date_yyyy_mm_dd || 'Unknown'}</span>
                        <span>Departure: ${flight.departure_time_hhmm || '-'}</span>
                        <span>Arrival: ${flight.arrival_time_hhmm || '-'}</span>
                        <span>Duration: ${flight.block_time_hhmm || 'Unknown'}</span>
                    </div>
                </div>
            `).join('');
        }

        this.showShadowbox('historyShadowbox');
    }

    showShadowbox(shadowboxId) {
        const shadowbox = document.getElementById(shadowboxId);
        if (shadowbox) {
            shadowbox.style.display = 'flex';
            // Prevent body scroll
            document.body.style.overflow = 'hidden';
        }
    }

    closeShadowbox(shadowboxId) {
        const shadowbox = document.getElementById(shadowboxId);
        if (shadowbox) {
            shadowbox.style.display = 'none';
            // Restore body scroll
            document.body.style.overflow = '';
        }
    }

    updateFooter() {
        const lastUpdatedElement = document.getElementById('lastUpdated');
        const aircraftCountElement = document.getElementById('aircraftCount');

        if (lastUpdatedElement && this.data.last_updated) {
            const date = new Date(this.data.last_updated);
            const timeString = date.toLocaleTimeString();
            lastUpdatedElement.textContent = `Last updated: ${timeString}`;
        }

        if (aircraftCountElement) {
            const count = this.data.planes?.length || 0;
            aircraftCountElement.textContent = `${count} aircraft tracked`;
        }
    }

    // Public method to request specific data
    requestData(dataType) {
        if (this.socket?.connected) {
            this.socket.emit('request_data', { type: dataType });
        }
    }
}

// Add touch feedback CSS class
const style = document.createElement('style');
style.textContent = `
    .touching {
        transform: scale(0.95) !important;
        opacity: 0.7 !important;
        transition: transform 0.1s ease, opacity 0.1s ease !important;
    }
`;
document.head.appendChild(style);

// Initialize app when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.airtracker = new AirTrackerApp();
});

// Export for debugging
window.AirTrackerApp = AirTrackerApp;