// --- Globals ---
let map = L.map('map').setView([-0.42, 36.95], 9); // Default Nyeri
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { 
    attribution: '© OpenStreetMap contributors' 
}).addTo(map);

let geeLayer = null;
let tsChart = null;
let pieChart = null;
let currentMode = 'raster'; // 'raster', 'vector', or 'terrain'

// --- VIEW SWITCHING LOGIC ---
function switchView(viewName, btnElement) {
    // 1. Update Buttons State
    const buttons = document.querySelectorAll('.tab-btn');
    buttons.forEach(btn => btn.classList.remove('active'));
    btnElement.classList.add('active');

    // 2. Set Global Mode
    currentMode = viewName;

    // 3. UI Adjustments
    const datasetSelect = document.getElementById('dataset');
    const chartCard = document.querySelector('.chart-card');
    const mapCard = document.querySelector('.map-card');

    if (currentMode === 'raster') {
        // --- RASTER MODE ---
        datasetSelect.disabled = false;
        datasetSelect.parentElement.style.opacity = '1';
        
        // Show Chart, Reset Map Width
        if (chartCard) chartCard.style.display = 'flex';
        if (mapCard) mapCard.style.flex = '2'; // Restores grid ratio
        
    } else {
        // --- VECTOR / TERRAIN MODE ---
        datasetSelect.disabled = true;
        datasetSelect.parentElement.style.opacity = '0.5';
        
        // Hide Chart, Expand Map
        if (chartCard) chartCard.style.display = 'none';
        if (mapCard) mapCard.style.flex = '100%'; // Forces full width
    }

    // 4. Force Map Resize
    setTimeout(() => { map.invalidateSize(); }, 200);

    // 5. Trigger Data Update
    updateDashboard();
}

// --- INITIALIZATION ---
function initCharts() {
    const ctxTs = document.getElementById('timeSeriesChart').getContext('2d');
    tsChart = new Chart(ctxTs, {
        type: 'line',
        data: { labels: [], datasets: [{ label: 'Value', data: [], borderColor: '#2E7D32', backgroundColor: 'rgba(46, 125, 50, 0.1)', borderWidth: 2, tension: 0.3, fill: true }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false } }, scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 8 } }, y: { beginAtZero: false, grid: { color: 'rgba(0,0,0,0.05)' } } } }
    });

    const ctxPie = document.getElementById('landCoverChart').getContext('2d');
    pieChart = new Chart(ctxPie, {
        type: 'doughnut',
        data: { labels: [], datasets: [{ data: [], backgroundColor: [], borderColor: '#fff', borderWidth: 1 }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'right', labels: { boxWidth: 12, font: { size: 11 } } } }, cutout: '60%' }
    });
}

// --- DYNAMIC UPDATES ---

async function updateLandCoverChart(region, year) {
    const yearSpan = document.getElementById('current-year');
    if (yearSpan) yearSpan.innerText = year;
    try {
        const response = await fetch('/api/get_landcover_pie', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ region: region, year: year })
        });
        const landCoverData = await response.json();
        
        if (Object.keys(landCoverData).length === 0) {
            pieChart.data.labels = ['No Data']; pieChart.data.datasets[0].data = [1]; pieChart.data.datasets[0].backgroundColor = ['#e0e0e0']; pieChart.update(); return;
        }
        
        const labels = []; const data = []; const backgroundColors = [];
        const sortedEntries = Object.entries(landCoverData).sort((a, b) => b[1].area - a[1].area);
        for (const [k, v] of sortedEntries) {
            if (labels.length < 8 && v.area > 0) { labels.push(k); data.push(v.area); backgroundColors.push(v.color); }
        }
        
        pieChart.data.labels = labels; pieChart.data.datasets[0].data = data; pieChart.data.datasets[0].backgroundColor = backgroundColors;
        pieChart.options.plugins.tooltip.callbacks.label = function(context) {
            const total = data.reduce((a, b) => a + b, 0);
            const percentage = total > 0 ? ((context.parsed / total) * 100).toFixed(1) : 0;
            return `${context.label}: ${context.parsed.toFixed(1)} km² (${percentage}%)`;
        };
        pieChart.update();
    } catch (error) { console.error("Error updating pie chart:", error); }
}

function updateLegend(dataset, stats = null) {
    const gradBar = document.querySelector('.gradient-bar');
    const legendLow = document.getElementById('legend-low');
    const legendHigh = document.getElementById('legend-high');
    document.getElementById('legend').style.display = 'flex';

    // Parse stats for legend
    let minVal = 'Low'; 
    let maxVal = 'High';
    
    // Check if stats is an array (from new backend structure) or obj
    // We will rely on hardcoded ranges mostly for visualization consistency
    
    switch(dataset) {
        case 'LST':
            gradBar.style.background = 'linear-gradient(to right, #313695, #4575b4, #ffffbf, #fdae61, #d73027, #a50026)';
            legendLow.innerText = '15°C'; legendHigh.innerText = '45°C';
            break;
        case 'NDVI':
            gradBar.style.background = 'linear-gradient(to right, #d73027, #fdae61, #ffffbf, #a6d96a, #1a9850)';
            legendLow.innerText = '-0.2'; legendHigh.innerText = '0.8';
            break;
        case 'LULC':
            gradBar.style.background = 'linear-gradient(to right, #419bdf, #397d49, #e49635, #c4281b)';
            legendLow.innerText = 'Water'; legendHigh.innerText = 'Urban';
            break;
        case 'TERRAIN':
            gradBar.style.background = 'linear-gradient(to right, #006600, #fff700, #ab5500, #ffffff)';
            legendLow.innerText = '500m'; legendHigh.innerText = '4000m';
            break;
        case 'VECTOR':
            gradBar.style.background = '#000';
            legendLow.innerText = 'Boundary'; legendHigh.innerText = '';
            break;
        default:
            gradBar.style.background = 'linear-gradient(to right, #000, #fff)';
            legendLow.innerText = 'Dark'; legendHigh.innerText = 'Light';
    }
}

// --- UPDATED: Dynamic Stats Rendering ---
function updateStats(statsData) {
    // statsData is expected to be an array: [{label: '...', value: '...'}, ...]
    const statLabels = document.querySelectorAll('.stat-label');
    const statValues = document.querySelectorAll('.stat-value');

    // Clear previous
    statLabels.forEach(el => el.innerText = '--');
    statValues.forEach(el => el.innerText = '--');

    if (Array.isArray(statsData)) {
        statsData.forEach((item, index) => {
            if (index < statLabels.length) {
                statLabels[index].innerText = item.label;
                statValues[index].innerText = item.value;
            }
        });
    }
}

function zoomToCounty(bounds) {
    if (bounds && bounds.length >= 4) {
        const latLngBounds = L.latLngBounds([bounds[0][1], bounds[0][0]], [bounds[2][1], bounds[2][0]]);
        map.fitBounds(latLngBounds, { padding: [30, 30], maxZoom: 12 });
    }
}

// --- MAIN CONTROLLER ---
async function updateDashboard() {
    const btn = document.getElementById('apply-btn');
    const originalText = btn.innerHTML;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Processing...';
    btn.disabled = true;

    const region = document.getElementById('region').value;
    const startDate = document.getElementById('start-date').value;
    const endDate = document.getElementById('end-date').value;
    const year = document.getElementById('year-select').value; 

    // Determine Dataset
    let dataset;
    if (currentMode === 'vector') dataset = 'VECTOR';
    else if (currentMode === 'terrain') dataset = 'TERRAIN';
    else dataset = document.getElementById('dataset').value;

    const payload = { region, dataset, start: startDate, end: endDate, year };

    try {
        const mapRes = await fetch('/api/update_map', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        
        if (!mapRes.ok) throw new Error(`Map API error`);
        const mapData = await mapRes.json();

        if (geeLayer) map.removeLayer(geeLayer);
        geeLayer = L.tileLayer(mapData.tile_url, { attribution: 'Google Earth Engine | ' + dataset }).addTo(map);

        if (mapData.bounds) zoomToCounty(mapData.bounds);
        updateLegend(dataset, mapData.stats);
        updateStats(mapData.stats); // Pass the new stats list directly

        // Update Charts
        if (currentMode === 'raster' && dataset !== 'LULC' && dataset !== 'TRUE_COLOR') {
             const chartRes = await fetch('/api/get_chart', {
                method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
            });
            const chartData = await chartRes.json();
            tsChart.data.labels = chartData.dates || [];
            tsChart.data.datasets[0].data = chartData.values || [];
            tsChart.data.datasets[0].label = dataset;
            tsChart.update();
        } else {
            tsChart.data.labels = []; tsChart.data.datasets[0].data = []; tsChart.update();
        }

        await updateLandCoverChart(region, year);

    } catch (error) {
        console.error(error);
        alert("Error loading data.");
    } finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

// --- APP INIT ---
function initDashboard() {
    initCharts();
    const endDate = new Date();
    const startDate = new Date();
    startDate.setFullYear(startDate.getFullYear() - 1);
    document.getElementById('end-date').value = endDate.toISOString().split('T')[0];
    document.getElementById('start-date').value = startDate.toISOString().split('T')[0];
    updateDashboard();
}

// --- FOOTER ACTIONS ---
async function downloadData() {
    const btn = document.getElementById('btn-download');
    const originalText = btn.innerHTML;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Downloading...';
    btn.disabled = true;

    // Determine dataset for CSV
    let dataset;
    if (currentMode === 'vector') dataset = 'VECTOR';
    else if (currentMode === 'terrain') dataset = 'TERRAIN';
    else dataset = document.getElementById('dataset').value;

    const payload = {
        region: document.getElementById('region').value,
        dataset: dataset,
        start: document.getElementById('start-date').value,
        end: document.getElementById('end-date').value
    };
    
    try {
        const response = await fetch('/api/download_csv', {
            method: 'POST', 
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        if (!response.ok) throw new Error('Download failed');
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${payload.region}_${payload.dataset}_Data.csv`;
        document.body.appendChild(a);
        a.click();
        a.remove();
    } catch (error) {
        console.error("Download error:", error);
    } finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

function generateReport() {
    const btn = document.getElementById('btn-report');
    const originalText = btn.innerHTML;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Preparing...';
    setTimeout(() => {
        btn.innerHTML = originalText;
        window.print();
    }, 1000);
}


document.addEventListener('DOMContentLoaded', initDashboard);