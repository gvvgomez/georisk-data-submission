import streamlit as st
import geopandas as gpd
import pandas as pd
import requests
import zipfile
import io
import os
import shutil
from shapely.geometry import box
import leafmap.foliumap as leafmap  # Integrated high-fidelity GIS engine

# ==========================================
# 1. CONSTANTS & SYSTEM CONFIGURATION
# ==========================================
st.set_page_config(page_title="GeoRiskPH LDS Portal", layout="wide")

PH_MIN_LON, PH_MAX_LON = 114.1, 126.6
PH_MIN_LAT, PH_MAX_LAT = 4.6, 21.2

MUNICIPAL_URL = "https://ulap-nga.georisk.gov.ph/arcgis/rest/services/PSA/Municipal_2020/MapServer/0/query"

TEMPLATE_DICT = {
    "Building Footprints": "Polygon", "Pre-Disaster Land Use": "Polygon",
    "Post-Disaster Land Use": "Polygon", "Municipal Boundary": "Polygon",
    "Barangay Boundary": "Polygon", "Bridges": "LineString", "Roads": "LineString",
    "Major Decision Areas": "Polygon", "Railways": "LineString", "Power Lines": "LineString",
    "Water Lines": "LineString", "Communication Network": "LineString",
    "Drainage and Sewer Lines": "LineString", "Coastal Resources": "Polygon",
    "Municipal Waters": "Polygon", "Ancillary Road Facilities": "Point",
    "Communication Services Facilities": "Point", "Power Plants and Renewable Energy Facilities": "Point",
    "Power Substations": "Point", "Railway Facilities": "Point", "Transport-related Projects": "Point",
    "Transportation Terminals": "Point", "Level II Water Supply System": "Point",
    "Level III Water Supply System": "Point", "Overlay Use": "Polygon",
    "Zoning Ordinance": "Polygon", "Slope": "Polygon",
}

# Initialize session state tracking vectors securely
if "processed_layers" not in st.session_state:
    st.session_state.processed_layers = []
if "screening_triggered" not in st.session_state:
    st.session_state.screening_triggered = False
if "snap_region" not in st.session_state:
    st.session_state.snap_region = "Click to select"
if "snap_province" not in st.session_state:
    st.session_state.snap_province = "Click to select"
if "snap_muni" not in st.session_state:
    st.session_state.snap_muni = "Click to select"

# ==========================================
# 2. LIVE ARCGIS REST ENDPOINT CLIENTS
# ==========================================
@st.cache_data(ttl=3600)
def fetch_location_hierarchy_live():
    """Queries official Municipal 2020 REST endpoint to populate dropdown selectors."""
    params = {
        "where": "1=1",
        "outFields": "reg_name,prov_name,city_name",
        "returnGeometry": "false",
        "f": "json"
    }
    try:
        res = requests.get(MUNICIPAL_URL, params=params, timeout=15).json()
        features = [f['attributes'] for f in res.get('features', [])]
        return pd.DataFrame(features)
    except Exception:
        return pd.DataFrame(columns=['reg_name', 'prov_name', 'city_name'])

@st.cache_data(ttl=600)
def fetch_reference_bounds_live(province, municipality):
    """Queries official municipal boundary geometry from GeoRiskPH MapServer layers for validation."""
    escaped_province = province.replace("'", "''")
    escaped_muni = municipality.replace("'", "''")
    
    params = {
        "where": f"prov_name = '{escaped_province}' AND city_name = '{escaped_muni}'",
        "outFields": "*",
        "outSR": "4326",
        "f": "geojson"
    }
    try:
        res = requests.get(MUNICIPAL_URL, params=params, timeout=15)
        if res.status_code == 200 and "error" not in res.text.lower():
            gdf = gpd.read_file(io.StringIO(res.text))
            return gdf if not gdf.empty else None
    except Exception:
        return None
    return None

# ==========================================
# 3. USER INTERFACE LAYOUT
# ==========================================
st.image("https://georisk.gov.ph/images/brand/GeoRiskPH.png", width=250)
st.title("Local Data Submission Portal")

st.markdown("""
GeoRisk Philippines (GeoRiskPH) is a multi-agency initiative led by the Philippine Institute of Volcanology and Seismology (DOST-PHIVOLCS). Applications developed by the GeoRiskPH include HazardHunterPH, GeoAnalyticsPH, and GeoMapperPH, among others. *By using this portal, you are authorizing DOST-PHIVOLCS to collect and process your local data for products and services improvement. All information provided will be treated with utmost confidentiality and only for the purpose stated above in accordance with Republic Act No. 10173 or the Data Privacy Act of 2012.*
""")

st.markdown("---")

# Section 1: Contact Information
st.header("👤 Contact Information")
col1, col2 = st.columns(2)
with col1:
    full_name = st.text_input("Full Name", placeholder="e.g., Juan P. Dela Cruz")
    email = st.text_input("Active Personal Email Address", placeholder="e.g., juandelacruz@mail.com")
    mobile = st.text_input("Mobile Number", placeholder="e.g., 091234567890")
with col2:
    affiliation_options = [
        "Click to select", "Academe", "Local Government Unit", "National Government Agency",
        "Non-Government Organization", "Multinational Corporation", "Large Enterprise",
        "Micro/Small/Medium Enterprise", "Individual - Filipino", "Individual - Foreigner"
    ]
    event_options = [
        "Click to select", "GeoRiskPH Regular Training", "GeoRiskPH Training of Trainers",
        "GeoRiskPH Regional Training", "GeoRiskPH Convention", "PlanSmart for Sustainable Human Settlements"
    ]
    affiliation = st.selectbox("Affiliation", options=affiliation_options, index=0)
    office_name = st.text_input("Full Name of Office/Agency/Organization", placeholder="e.g., Quezon City Disaster Risk Reduction and Management Office")
    event_type = st.selectbox("GeoRiskPH Event Attended", options=event_options, index=0)

st.markdown("---")

# Section 2: Local Dataset Upload
st.header("📁 Data Submission")
st.subheader("File Upload")
uploaded_file = st.file_uploader(
    "Click button or drag-and-drop to upload. Maximum file size: 200 MB.",
    type=['zip', 'kml', 'kmz', 'gpkg', 'csv'],
    accept_multiple_files=False
)

st.markdown("Accepted formats: zipped shapefile (**shp**), zipped file geodatabase (**gdb**), geopackage (**gpkg**), keyhole markup (**kml**/**kmz**), and comma-separated values (**csv**) with latitude and longitude coordinates.")
st.image("accepted_formats.png", width="stretch")

st.subheader("Geographic Extent")
hierarchy_df = fetch_location_hierarchy_live()

if hierarchy_df.empty:
    st.error("⚠️ Connection failure. Verify if your internet access can reach the ulap-nga web services.")
    selected_region = "Click to select"
    selected_province = "Click to select"
    selected_municipality = "Click to select"
else:
    reg_col, prov_col, mun_col = st.columns(3)

    with reg_col:
        regions = sorted([str(r) for r in hierarchy_df['reg_name'].dropna().unique()])
        selected_region = st.selectbox("Region", options=["Click to select"] + regions)

    with prov_col:
        if selected_region != "Click to select":
            prov_list = sorted([str(p) for p in hierarchy_df[hierarchy_df['reg_name'] == selected_region]['prov_name'].dropna().unique()])
            selected_province = st.selectbox("Province", options=["Click to select"] + prov_list)
        else:
            selected_province = st.selectbox("Province", options=["Click to select"], disabled=True)

    with mun_col:
        if selected_province != "Click to select":
            muni_list = sorted([str(m) for m in hierarchy_df[hierarchy_df['prov_name'] == selected_province]['city_name'].dropna().unique()])
            selected_municipality = st.selectbox("Municipality/City", options=["Click to select"] + muni_list)
        else:
            selected_municipality = st.selectbox("Municipality/City", options=["Click to select"], disabled=True)

st.markdown("Please provide the geographic extent or coverage of the data to be submitted, not the address of the office or organization you are representing.")

# ==========================================
# 4. PROCESSING & INGESTION PIPELINE
# ==========================================
if st.button("🚀 Proceed to Extent Validation", type="primary"):
    if not full_name or not email or not mobile or not office_name:
        st.error("Please fill up all contact information fields.")
    elif affiliation == "Click to select":
        st.error("Please select a valid profile affiliation.")
    elif uploaded_file is None:
        st.error("Please upload a valid dataset.")
    elif event_type == "Click to select":
        st.error("Please specify the GeoRiskPH event you attended.")
    elif selected_municipality == "Click to select":
        st.error("Please specify the target location extent parameters.")
    else:
        file_ext = os.path.splitext(uploaded_file.name)[1].lower()
        
        # TIER 1 Validation: Explicitly block non-accepted file extensions globally
        ACCEPTED_EXTENSIONS = ['.zip', '.geojson', '.kml', '.kmz', '.gpkg', '.csv']
        if file_ext not in ACCEPTED_EXTENSIONS:
            st.error(f"❌ **Unsupported File Type**: `{file_ext}` files are not accepted by the LDS pipeline. Please provide one of the standard formats listed above.")
        else:
            st.info("Parsing file geometry formats into pipeline session container...")
            
            temp_dir = "./temp_screening_workspace"
            shutil.rmtree(temp_dir, ignore_errors=True)
            os.makedirs(temp_dir, exist_ok=True)
            
            st.session_state.processed_layers = []
            shapefile_validation_failed = False
            
            try:
                # --- CSV INTERCEPT ---
                if file_ext == '.csv':
                    csv_path = os.path.join(temp_dir, uploaded_file.name)
                    with open(csv_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    df = pd.read_csv(csv_path)
                    lat_col = next((c for c in df.columns if c.lower() in ['latitude', 'lat', 'y']), None)
                    lon_col = next((c for c in df.columns if c.lower() in ['longitude', 'lon', 'x']), None)
                    
                    if lat_col and lon_col:
                        clean_df = df.dropna(subset=[lat_col, lon_col])
                        gdf = gpd.GeoDataFrame(clean_df, geometry=gpd.points_from_xy(clean_df[lon_col], clean_df[lat_col]), crs="EPSG:4326")
                        if not gdf.empty:
                            st.session_state.processed_layers.append({"name": uploaded_file.name, "fmt": file_ext, "gdf": gdf})
                
                # --- ZIP ARCHIVES (Shapefiles or GDB bundles) ---
                elif file_ext == '.zip':
                    zip_path = os.path.join(temp_dir, uploaded_file.name)
                    with open(zip_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    
                    # Open zip in memory to scan and inventory its contents first
                    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                        archive_files = zip_ref.namelist()
                        
                        # Check if this zip contains an Esri File Geodatabase (.gdb folder wrapper)
                        gdb_directories = set()
                        for f_path in archive_files:
                            if '.gdb/' in f_path.lower():
                                # Extract the exact path up to the '.gdb' directory name
                                parts = f_path.split('/')
                                for idx, part in enumerate(parts):
                                    if part.lower().endswith('.gdb'):
                                        gdb_path_prefix = '/'.join(parts[:idx+1])
                                        gdb_directories.add(gdb_path_prefix)
                        
                        # --- CASE A: Handle File Geodatabase Extraction ---
                        if gdb_directories:
                            zip_ref.extractall(temp_dir)
                            import fiona
                            
                            for gdb_rel_path in gdb_directories:
                                full_gdb_path = os.path.join(temp_dir, gdb_rel_path.replace('/', os.sep))
                                gdb_name = os.path.basename(full_gdb_path)
                                
                                try:
                                    # File Geodatabases can house multiple feature classes. Loop through each layer.
                                    layers = fiona.listlayers(full_gdb_path)
                                    for layer_name in layers:
                                        gdf = gpd.read_file(full_gdb_path, layer=layer_name)
                                        if not gdf.empty:
                                            # Using "GDB Name > Layer Name" to keep the map legend precise
                                            st.session_state.processed_layers.append({
                                                "name": f"{gdb_name} [{layer_name}]",
                                                "fmt": ".gdb",
                                                "gdf": gdf
                                            })
                                except Exception as e:
                                    st.warning(f"⚠️ Failed to parse Geodatabase layer components: {str(e)}")
                        
                        # --- CASE B: Handle Standard Shapefiles / Loose Vectors ---
                        else:
                            shapefile_components = {}
                            for f_path in archive_files:
                                if f_path.endswith('/') or '__MACOSX' in f_path or '.DS_Store' in f_path:
                                    continue
                                base_name, ext = os.path.splitext(os.path.basename(f_path))
                                ext = ext.lower()
                                
                                if ext in ['.shp', '.shx', '.dbf', '.prj']:
                                    dir_prefix = os.path.dirname(f_path)
                                    lookup_key = os.path.join(dir_prefix, base_name)
                                    if lookup_key not in shapefile_components:
                                        shapefile_components[lookup_key] = set()
                                    shapefile_components[lookup_key].add(ext)
                            
                            # TIER 2 Validation: Check for mandatory Esri Shapefile structural components
                            required_components = {'.shp', '.shx', '.dbf', '.prj'}
                            missing_reports = []
                            
                            for shp_base, found_exts in shapefile_components.items():
                                missing_exts = required_components - found_exts
                                if missing_exts:
                                    missing_reports.append(
                                        f"• `{os.path.basename(shp_base)}` is missing mandatory components: **{', '.join(missing_exts)}**"
                                    )
                            
                            if missing_reports:
                                shapefile_validation_failed = True
                                st.error("❌ **Invalid Shapefile Structure**: The uploaded zip file contains an incomplete Esri Shapefile cluster.")
                                for report in missing_reports:
                                    st.markdown(report)
                                st.warning("💡 *Note: Every shapefile requires a matching `.shp` (geometry), `.shx` (index), `.dbf` (attributes), and `.prj` (projection/CRS details) bundled together.*")
                            
                            # Proceed with standard extraction if shapefiles match specification boundaries
                            if not shapefile_validation_failed:
                                zip_ref.extractall(temp_dir)
                                
                                for root, _, files in os.walk(temp_dir):
                                    for file in files:
                                        full_path = os.path.join(root, file)
                                        internal_ext = os.path.splitext(file)[1].lower()
                                        if internal_ext in ['.shp', '.geojson', '.gpkg', '.kml']:
                                            try:
                                                gdf = gpd.read_file(full_path)
                                                if not gdf.empty:
                                                    st.session_state.processed_layers.append({"name": file, "fmt": internal_ext, "gdf": gdf})
                                            except:
                                                pass
                
                # --- DIRECT VECTORS (.geojson, .kml, .kmz, .gpkg) ---
                else:
                    direct_path = os.path.join(temp_dir, uploaded_file.name)
                    with open(direct_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    gdf = gpd.read_file(direct_path)
                    if not gdf.empty:
                        st.session_state.processed_layers.append({"name": uploaded_file.name, "fmt": file_ext, "gdf": gdf})
                
                # Assign map operational states depending on structural safety results
                if st.session_state.processed_layers and not shapefile_validation_failed:
                    st.session_state.screening_triggered = True
                    st.session_state.snap_region = selected_region
                    st.session_state.snap_province = selected_province
                    st.session_state.snap_muni = selected_municipality
                else:
                    if not shapefile_validation_failed:
                        st.error("No extractable spatial components found inside upload package.")
                    st.session_state.screening_triggered = False
                    
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)

st.markdown("---")

# ==========================================
# 5. PERSISTENT EVALUATION LAYER DISPLAY
# ==========================================
if st.session_state.screening_triggered and st.session_state.processed_layers:
    
    st.header("🗺️ Map Preview")
    
    # Initialize a clean, native Folium Map centered on the Philippines
    import folium
    import streamlit.components.v1 as components
    
    # 1. Base Map Setup with Esri Imagery + OpenStreetMap option
    m1 = folium.Map(location=[13.0, 122.0], zoom_start=6, tiles=None)
    
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri",
        name="Esri World Imagery",
        overlay=False,
        control=True
    ).add_to(m1)
    
    folium.TileLayer(
        tiles="openstreetmap",
        name="OpenStreetMap",
        overlay=False,
        control=True
    ).add_to(m1)

    # 2. Add Uploaded Datasets using file names directly as Layer Names
    active_gdfs_for_zoom = []
    
    # Distinct hex colors to separate multiple layers if uploaded
    palette = ["#3388ff", "#00ffff", "#ff0000", "#ffaa00", "#9900ff"]
    
    for idx, layer in enumerate(st.session_state.processed_layers):
        name = layer["name"]
        gdf = layer["gdf"]
        
        if gdf.crs is not None:
            gdf_4326 = gdf.to_crs(epsg=4326) if gdf.crs.to_epsg() != 4326 else gdf
            active_gdfs_for_zoom.append(gdf_4326)
            
            # Convert timestamp columns to text strings to ensure clean JSON translation
            gdf_clean = gdf_4326.copy()
            for col in gdf_clean.select_dtypes(include=['datetime64', 'datetime', 'datetimetz']).columns:
                gdf_clean[col] = gdf_clean[col].astype(str)
            
            # Select color from palette matching layer index
            layer_color = palette[idx % len(palette)]
            
            # Inject Feature Collection directly into Folium Layer container
            geo_json_layer = folium.GeoJson(
                gdf_clean.__geo_interface__,
                name=name,
                style_function=lambda x, color=layer_color: {
                    "fillColor": color,
                    "color": color,
                    "weight": 2.5,
                    "fillOpacity": 0.15
                }
            )
            geo_json_layer.add_to(m1)

    # 3. Add Native Floating Leaflet Layer Toggle Control Menu (Top Right)
    folium.LayerControl(position="topright", collapsed=False).add_to(m1)

    # 4. Automatically adjust map bounds to center on data geometries safely
    if active_gdfs_for_zoom:
        import pandas as pd
        combined_all = gpd.GeoDataFrame(pd.concat(active_gdfs_for_zoom, ignore_index=True), crs="EPSG:4326")
        minx, miny, maxx, maxy = combined_all.total_bounds
        m1.fit_bounds([[miny, minx], [maxy, maxx]])

    # Pure memory display bypasses Windows permission and file locks
    map_html = m1._repr_html_()
    components.html(map_html, height=500, scrolling=False)

    # ------------------------------------------
    # PERSISTENT PROPERTIES MATRIX WITH GEOMETRY TRACKING
    # ------------------------------------------
    st.subheader("📊 Layer Properties and Template Matching")
    
    for i, layer in enumerate(st.session_state.processed_layers):
        name = layer["name"]
        fmt = layer["fmt"]
        gdf = layer["gdf"]
        
        detected_geom = str(gdf.geom_type.dropna().iloc[0]) if not gdf.empty else "Unknown"
        crs_str = gdf.crs.name if gdf.crs else "Undefined"
        
        # Calculate total spatial records/rows within this layer vector
        feature_count = len(gdf) if not gdf.empty else 0
        
        with st.container():
            col_a, col_b, col_c, col_d, col_e, col_f = st.columns([2, 1, 1.2, 1.8, 1.2, 2.5])
            with col_a:
                st.text_input("File Name", value=name, disabled=True, key=f"fn_matrix_{i}")
            with col_b:
                st.text_input("Format", value=fmt.upper(), disabled=True, key=f"fmt_matrix_{i}")
            with col_c:
                st.text_input("Geometry", value=detected_geom, disabled=True, key=f"geom_matrix_{i}")
            with col_d:
                st.text_input("Coordinate System", value=crs_str, disabled=True, key=f"crs_matrix_{i}")
            with col_e:
                st.text_input("Number of Features", value=str(feature_count), disabled=True, key=f"count_matrix_{i}")
            with col_f:
                target_selection = st.selectbox(
                    "Target Feature Template Match",
                    options=list(TEMPLATE_DICT.keys()),
                    key=f"target_temp_{name}_{i}"
                )
                
            expected_geom = TEMPLATE_DICT[target_selection]
            if expected_geom.lower() not in detected_geom.lower():
                st.error(f"❌ **Geometry Conflict**: Template `{target_selection}` expects **{expected_geom}**, but the uploaded dataset contains **{detected_geom}** features.")
            else:
                st.success(f"✅ Geometry of `{target_selection}` matches with that of the uploaded dataset.")
            
            # ---------------------------------------------------------
            # ATTRIBUTE TABLE PREVIEW (Inserted right under validation)
            # ---------------------------------------------------------
            if not gdf.empty:
                # Drop spatial geometry coordinates for clean text-based tabular view
                df_preview = gdf.drop(columns=["geometry"], errors="ignore").head(5)
                st.dataframe(
                    df_preview, 
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.caption("ℹ️ No attribute data available for preview.")
                
        st.markdown("---")

# ------------------------------------------
    # 6. CENTRAL SUBMISSION GATEWAY PIPELINE
    # ------------------------------------------
    # Define your deployed Apps Script Web App URL gateway here
    API_GATEWAY_URL = "https://script.google.com/macros/s/AKfycbwwRnsU-GksEAi4hqhfh-yflTk-YcFXcQqwHH4omarDm2xr-tWFvmj2CnxZlz0kocG9/exec"

    if st.button("💾 Submit for Official Processing", type="primary", use_container_width=True):
        with st.spinner("Uploading dataset bundle to Google Drive and documenting schema logs..."):
            
            compiled_layers_payload = []
            for idx, layer in enumerate(st.session_state.processed_layers):
                l_name = layer["name"]
                l_fmt = layer["fmt"]
                l_gdf = layer["gdf"]
                l_geom = str(l_gdf.geom_type.dropna().iloc[0]) if not l_gdf.empty else "Unknown"
                l_crs = l_gdf.crs.name if l_gdf.crs else "Undefined"
                
                # Fetch row lengths dynamically
                l_count = len(l_gdf) if not l_gdf.empty else 0
                
                selected_template = st.session_state.get(f"target_temp_{l_name}_{idx}", "Building Footprints")
                
                compiled_layers_payload.append({
                    "fileName": l_name,
                    "fileFormat": l_fmt.upper(),
                    "geometry": l_geom,
                    "coordinateSystem": l_crs,
                    "featureCount": l_count, # Captures record count for this individual sub-layer
                    "templateMatch": selected_template
                })
            
            uploaded_file.seek(0)
            import base64
            file_bytes = uploaded_file.read()
            encoded_base64_string = base64.b64encode(file_bytes).decode("utf-8")
            current_file_ext = os.path.splitext(uploaded_file.name)[1].lower()
            
            # Build unified JSON payload
            payload = {
                "timestamp": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
                "fullName": full_name,
                "email": email,
                "mobile": mobile,
                "affiliation": affiliation,
                "officeName": office_name,
                "eventType": event_type, # 🌟 Sent securely to Apps Script
                "region": st.session_state.snap_region,
                "province": st.session_state.snap_province,
                "municipality": st.session_state.snap_muni,
                "fileName": uploaded_file.name,
                "fileExtension": current_file_ext,
                "fileBase64": encoded_base64_string,
                "layers": compiled_layers_payload
            }
            
            # Execute transactional API call to Google Workspace API gateway
            try:
                response = requests.post(API_GATEWAY_URL, json=payload, timeout=60)
                if response.status_code == 200 and response.json().get("status") == "success":
                    st.balloons()
                    st.success("🎉 Data submission complete! GeoRiskPH has received your files and will provide updates regarding their integration into the system.")
                else:
                    error_details = response.json().get("message") if response.status_code == 200 else response.text
                    st.error(f"❌ Storage Pipeline Refusal: Failed to push data logs. System Message: {error_details}")
            except Exception as e:
                st.error(f"⚠️ Transmission Link Timeout: Could not connect to Google API Gateway endpoint. Details: {str(e)}")
        
        # This will store a flag indicating a submission attempt happened within this run
        st.session_state.submission_attempted = True

    # ------------------------------------------
    # REFRESH / RESET FLOW
    # ------------------------------------------
    # Show the reset option if a submission was attempted in the current session state
    if st.session_state.get("submission_attempted", False):
        st.markdown("---")
        if st.button("🔄 Make Another Submission", use_container_width=True):
            # Clear critical session state tracking variables if necessary
            if "processed_layers" in st.session_state:
                del st.session_state.processed_layers
            if "submission_attempted" in st.session_state:
                del st.session_state.submission_attempted
                
            # Force a clean app refresh/restart
            st.rerun()