from flask import Flask, render_template, jsonify, request, Response
import ee
import pandas as pd
import json

app = Flask(__name__)

# --- GEE Initialization ---
try:
    ee.Initialize(project='ee-c4708911')
except:
    try:
        ee.Authenticate()
        ee.Initialize(project='ee-c4708911')
    except Exception as e:
        print(f"GEE Auth Error: {e}")
        ee.Authenticate()
        ee.Initialize()

# --- Helper Functions ---

def get_geometry(county_name):
    """Fetches County Geometry from FAO GAUL"""
    return ee.FeatureCollection("FAO/GAUL/2015/level2") \
        .filter(ee.Filter.eq('ADM0_NAME', 'Kenya')) \
        .filter(ee.Filter.eq('ADM2_NAME', county_name)) \
        .geometry()

def get_ndvi_image(roi, start, end):
    def mask_clouds(img):
        qa = img.select('QA60')
        mask = qa.bitwiseAnd(1<<10).eq(0).And(qa.bitwiseAnd(1<<11).eq(0))
        return img.updateMask(mask).divide(10000)
    
    col = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED') \
        .filterDate(start, end).filterBounds(roi).map(mask_clouds) \
        .map(lambda img: img.addBands(img.normalizedDifference(['B8', 'B4']).rename('NDVI')))
    return col.select('NDVI').mean().clip(roi)

def get_lst_image(roi, start, end):
    def scale_lst(img):
        st = img.select('ST_B10').multiply(0.00341802).add(149.0).subtract(273.15).rename('LST')
        return img.addBands(st)
    col = ee.ImageCollection("LANDSAT/LC08/C02/T1_L2").filterDate(start, end).filterBounds(roi).map(scale_lst)
    return col.select('LST').mean().clip(roi)

def get_true_color_image(roi, start, end):
    def mask_clouds(img):
        qa = img.select('QA60')
        mask = qa.bitwiseAnd(1<<10).eq(0).And(qa.bitwiseAnd(1<<11).eq(0))
        return img.updateMask(mask).divide(10000)
    return ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filterDate(start, end).filterBounds(roi) \
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20)).map(mask_clouds).median().select(['B4', 'B3', 'B2']).clip(roi)

def get_dynamic_world_lulc(roi, start, end):
    return ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1").filterDate(start, end).filterBounds(roi).select('label').mode().clip(roi)

def get_terrain_image(roi):
    dem = ee.Image('USGS/SRTMGL1_003').clip(roi)
    return dem.select('elevation')

def get_vector_overlay(county_name):
    fc = ee.FeatureCollection("FAO/GAUL/2015/level2") \
        .filter(ee.Filter.eq('ADM0_NAME', 'Kenya')) \
        .filter(ee.Filter.eq('ADM2_NAME', county_name))
    empty = ee.Image().byte()
    return empty.paint(featureCollection=fc, color=1, width=2)

# --- Routes ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/update_map', methods=['POST'])
def update_map():
    req = request.json
    region_name = req.get('region', 'Nyeri')
    dataset = req.get('dataset', 'NDVI')
    start = req.get('start', '2023-01-01')
    end = req.get('end', '2023-12-31')
    
    if dataset == 'LULC' and 'year' in req:
        year = req['year']
        start = f"{year}-01-01"
        end = f"{year}-12-31"

    roi = get_geometry(region_name)
    bounds_info = roi.bounds().getInfo()['coordinates'][0] 

    stats_data = []
    image = None
    vis = {}

    # --- 1. Raster Analysis ---
    if dataset == 'NDVI':
        image = get_ndvi_image(roi, start, end)
        vis = {'min': -0.2, 'max': 0.8, 'palette': ['#d73027', '#fdae61', '#ffffbf', '#a6d96a', '#1a9850']}
        reducers = ee.Reducer.mean().combine(ee.Reducer.minMax(), sharedInputs=True)
        raw = image.reduceRegion(reducer=reducers, geometry=roi, scale=1000, bestEffort=True).getInfo()
        
        stats_data = [
            {'label': 'Mean NDVI', 'value': round(raw.get('NDVI_mean', 0), 2)},
            {'label': 'Max Peak', 'value': round(raw.get('NDVI_max', 0), 2)},
            {'label': 'Min Low', 'value': round(raw.get('NDVI_min', 0), 2)}
        ]

    elif dataset == 'LST':
        image = get_lst_image(roi, start, end)
        vis = {'min': 0, 'max': 50, 'palette': ['#313695', '#4575b4', '#ffffbf', '#fdae61', '#d73027', '#a50026']}
        reducers = ee.Reducer.mean().combine(ee.Reducer.minMax(), sharedInputs=True)
        raw = image.reduceRegion(reducer=reducers, geometry=roi, scale=1000, bestEffort=True).getInfo()
        
        stats_data = [
            {'label': 'Avg Temp', 'value': f"{round(raw.get('LST_mean', 0), 1)} °C"},
            {'label': 'Max Temp', 'value': f"{round(raw.get('LST_max', 0), 1)} °C"},
            {'label': 'Min Temp', 'value': f"{round(raw.get('LST_min', 0), 1)} °C"}
        ]

    elif dataset == 'TRUE_COLOR':
        image = get_true_color_image(roi, start, end)
        vis = {'min': 0, 'max': 0.3}
        stats_data = [
            {'label': 'Composite', 'value': 'True Color'},
            {'label': 'Cloud Cover', 'value': '< 20%'},
            {'label': 'Sensor', 'value': 'Sentinel-2'}
        ]

    elif dataset == 'LULC':
        image = get_dynamic_world_lulc(roi, start, end)
        vis = {'min': 0, 'max': 8, 'palette': ['#419bdf', '#397d49', '#88b053', '#7a87c6', '#e49635', '#dfc35a', '#c4281b', '#a59b8f', '#b39fe1']}
        stats_data = [
            {'label': 'Dataset', 'value': 'Dynamic World'},
            {'label': 'Year', 'value': req.get('year', '2023')},
            {'label': 'Type', 'value': 'Categorical'}
        ]

    # --- 2. 3D Terrain Analysis ---
    elif dataset == 'TERRAIN':
        image = get_terrain_image(roi)
        vis = {
            'min': 500, 'max': 4000,
            'palette': ['006600', '002200', 'fff700', 'ab5500', 'aaaaaa', 'ffffff']
        }
        
        reducers = ee.Reducer.mean().combine(ee.Reducer.minMax(), sharedInputs=True)
        raw = image.reduceRegion(reducer=reducers, geometry=roi, scale=1000, bestEffort=True).getInfo()
        
        stats_data = [
            {'label': 'Avg Elevation', 'value': f"{int(raw.get('elevation_mean', 0))} m"},
            {'label': 'Highest Point', 'value': f"{int(raw.get('elevation_max', 0))} m"},
            {'label': 'Lowest Point', 'value': f"{int(raw.get('elevation_min', 0))} m"}
        ]

    # --- 3. Vector Analysis (Corrected) ---
    elif dataset == 'VECTOR':
        image = get_vector_overlay(region_name)
        vis = {'palette': '000000'}
        
        # FIX: Calculate raw area then round in Python
        raw_area = roi.area().divide(1e6).getInfo()
        area_sq_km = round(raw_area, 2)
        
        stats_data = [
            {'label': 'Admin Name', 'value': region_name},
            {'label': 'Total Area', 'value': f"{area_sq_km} km²"},
            {'label': 'Data Source', 'value': 'FAO GAUL'}
        ]

    if image is None:
         return jsonify({'error': 'Invalid dataset'})

    map_id = image.getMapId(vis)

    return jsonify({
        'tile_url': map_id['tile_fetcher'].url_format,
        'bounds': bounds_info, 
        'stats': stats_data 
    })

@app.route('/api/get_chart', methods=['POST'])
def get_chart():
    req = request.json
    region_name = req.get('region', 'Nyeri')
    dataset = req.get('dataset', 'NDVI')
    start = req.get('start', '2023-01-01')
    end = req.get('end', '2023-12-31')
    
    if dataset in ['LULC', 'TRUE_COLOR', 'VECTOR', 'TERRAIN']:
        return jsonify({'dates': [], 'values': []})

    roi = get_geometry(region_name)
    
    if dataset == 'NDVI':
        col = ee.ImageCollection('MODIS/061/MOD13Q1').filterDate(start, end).filterBounds(roi)
        def get_val(img):
            val = img.reduceRegion(ee.Reducer.mean(), roi, 500, bestEffort=True).get('NDVI')
            return ee.Feature(None, {'date': img.date().format('YYYY-MM-dd'), 'value': ee.Number(val).multiply(0.0001)})
    elif dataset == 'LST':
        col = ee.ImageCollection('MODIS/061/MOD11A2').filterDate(start, end).filterBounds(roi)
        def get_val(img):
            val = img.select('LST_Day_1km').reduceRegion(ee.Reducer.mean(), roi, 1000, bestEffort=True).get('LST_Day_1km')
            celsius = ee.Number(val).multiply(0.02).subtract(273.15)
            return ee.Feature(None, {'date': img.date().format('YYYY-MM-dd'), 'value': celsius})

    timeseries = col.map(get_val).getInfo()
    dates = [f['properties']['date'] for f in timeseries['features'] if f['properties']['value'] is not None]
    values = [round(f['properties']['value'], 2) for f in timeseries['features'] if f['properties']['value'] is not None]
    
    return jsonify({'dates': dates, 'values': values})

@app.route('/api/get_landcover_pie', methods=['POST'])
def get_landcover_pie():
    req = request.json
    region_name = req.get('region', 'Nyeri')
    year = req.get('year', '2023')
    start = f"{year}-01-01"; end = f"{year}-12-31"
    roi = get_geometry(region_name)
    
    dw = ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1").filterDate(start, end).filterBounds(roi).select('label').mode().clip(roi)
    area_image = ee.Image.pixelArea().addBands(dw)
    reduced = area_image.reduceRegion(reducer=ee.Reducer.sum().group(groupField=1, groupName='class_code'), geometry=roi, scale=100, bestEffort=True, maxPixels=1e9).getInfo()
    
    dw_classes = {0: {'name': 'Water', 'color': '#419bdf'}, 1: {'name': 'Trees', 'color': '#397d49'}, 2: {'name': 'Grass', 'color': '#88b053'}, 3: {'name': 'Flooded Veg', 'color': '#7a87c6'}, 4: {'name': 'Crops', 'color': '#e49635'}, 5: {'name': 'Shrub & Scrub', 'color': '#dfc35a'}, 6: {'name': 'Built Area', 'color': '#c4281b'}, 7: {'name': 'Bare Ground', 'color': '#a59b8f'}, 8: {'name': 'Snow & Ice', 'color': '#b39fe1'}}
    
    results = {}
    if 'groups' in reduced:
        for group in reduced['groups']:
            code = int(group['class_code'])
            area_sqm = group['sum']
            if code in dw_classes: results[dw_classes[code]['name']] = {'area': round(area_sqm/1e6, 2), 'color': dw_classes[code]['color']}
    return jsonify(results)

@app.route('/api/download_csv', methods=['POST'])
def download_csv():
    dataset = request.json.get('dataset')
    if dataset == 'LULC': return get_landcover_pie()
    data = get_chart().get_json() # Fix: Use get_json() on response object
    return Response(pd.DataFrame({'Date': data['dates'], 'Value': data['values']}).to_csv(index=False), mimetype="text/csv", headers={"Content-disposition": "attachment; filename=data.csv"})

if __name__ == '__main__':
    app.run(debug=True)