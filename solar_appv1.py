import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
import plotly.express as px
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
import pyproj
from shapely.geometry import shape

# --- APP CONFIGURATION ---
st.set_page_config(page_title="Solar Rooftop Planner", page_icon="☀️", layout="wide")

# --- STYLING ---
st.markdown("""
    <style>
    .main { background-color: #f0f2f6; }
    .stMetric { background-color: #ffffff; padding: 20px; border-radius: 12px; border: 1px solid #e0e0e0; }
    div[data-testid="stExpander"] { background-color: white; border-radius: 10px; }
    .stButton>button { width: 100%; border-radius: 8px; height: 3em; background-color: #FF4B4B; color: white; }
    </style>
""", unsafe_allow_html=True)

# Ensure sidebar stays on top in some deployments (Streamlit Cloud)
st.markdown("""
<style>
[data-testid="stSidebar"] { position: relative; z-index: 2000; }
.leaflet-container, iframe { z-index: 1000; }
</style>
""", unsafe_allow_html=True)

# --- CACHED LOGIC ---
def get_coordinates(address):
    try:
        # Identify the client to Nominatim (replace placeholder@example.com later if needed)
        geolocator = Nominatim(user_agent="solar_assessment_pro (placeholder@example.com)")
        geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1)
        location = geocode(address)
        if not location:
            return None, None, None
        return location.latitude, location.longitude, location.address
    except Exception as e:
        # Surface geocoding errors in the app UI/logs on Streamlit Cloud
        try:
            st.error(f"Geocoding error: {e}")
        except Exception:
            pass
        return None, None, None

@st.cache_data(ttl=3600)
def fetch_archive_data(lat, lon, start_date, end_date):
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": lat, "longitude": lon,
        "start_date": start_date, "end_date": end_date,
        "hourly": "shortwave_radiation", "timezone": "auto"
    }
    try:
        res = requests.get(url, params=params, timeout=20)
        res.raise_for_status()
        j = res.json()
        if 'hourly' not in j or 'shortwave_radiation' not in j.get('hourly', {}):
            # Return snippet for debugging
            return None, res.status_code, res.text[:500]
        return j, res.status_code, None
    except Exception as e:
        # Try to return any available response snippet for debugging
        try:
            return None, getattr(res, 'status_code', None), getattr(res, 'text', str(e))[:500]
        except Exception:
            return None, None, str(e)[:500]


def calculate_geodesic_area(geojson_geometry):
    """Calculate the geodesic area of a GeoJSON geometry in square meters."""
    s = shape(geojson_geometry)
    geod = pyproj.Geod(ellps="WGS84")
    area, _ = geod.geometry_area_perimeter(s)
    return abs(area)

# --- SIDEBAR INPUTS ---
st.sidebar.header("🏠 Property Details")
address_input = st.sidebar.text_input("Property Address", "Pune, Maharashtra")
monthly_bill = st.sidebar.number_input("Avg. Monthly Bill (₹)", value=3000, step=500)
electricity_rate = st.sidebar.slider("Electricity Rate (₹/kWh)", 5.0, 15.0, 8.5)

st.sidebar.header("🔌 System Capacity")
sys_capacity = st.sidebar.slider("Proposed System Size (kW)", 1.0, 50.0, 5.0)
sys_efficiency = st.sidebar.slider("System Efficiency (%)", 50, 95, 78) / 100

# Debug and manual inputs to help Streamlit Cloud troubleshooting
debug = st.sidebar.checkbox("DEBUG mode", False)
use_manual = st.sidebar.checkbox("Enter lat/lon manually", False)
manual_lat = None
manual_lon = None
if use_manual:
    manual_lat = st.sidebar.number_input("Latitude", value=18.5204, format="%.6f")
    manual_lon = st.sidebar.number_input("Longitude", value=73.8567, format="%.6f")

# --- MAIN PAGE ---
st.title("☀️ Solar Rooftop Self-Assessment")
st.write("Determine your solar potential, savings, and environmental contribution in seconds.")

if address_input or use_manual:
    if use_manual:
        lat = manual_lat
        lon = manual_lon
        full_address = f"Manual: {lat}, {lon}"
    else:
        lat, lon, full_address = get_coordinates(address_input)

    if debug:
        st.sidebar.write("Address input:", address_input)
        st.sidebar.write("Geocode result:", lat, lon, full_address)

    if lat:
        st.info(f"📍 **Analyzing:** {full_address}")
        
        # Tabs for different views
        tab_summary, tab_monthly, tab_hourly, tab_area, tab_guide = st.tabs([
            "💰 Financial & Impact", 
            "📅 Monthly Averages", 
            "📈 Hourly Detail", 
            "� Rooftop Area",
            "�📖 How it Works"
        ])

        # Fetch 1 full year of data for calculations
        # Using 2023 as a baseline for "Typical Year"
        with st.spinner("Calculating solar yields..."):
            data, status_code, resp_snip = fetch_archive_data(lat, lon, "2023-01-01", "2023-12-31")

        if debug:
            st.sidebar.write("Archive fetch status:", status_code)
            if resp_snip:
                st.sidebar.write("Archive response snippet:", resp_snip)

        if data:
            df = pd.DataFrame({
                "Timestamp": pd.to_datetime(data['hourly']['time']),
                "ghi": data['hourly']['shortwave_radiation']
            })
            df['production'] = (df['ghi'] / 1000) * sys_capacity * sys_efficiency
            
            # --- TAB 1: FINANCIAL & IMPACT ---
            with tab_summary:
                annual_yield = df['production'].sum()
                monthly_yield = annual_yield / 12
                annual_savings = annual_yield * electricity_rate
                
                c1, c2, c3 = st.columns(3)
                c1.metric("Est. Monthly Generation", f"{monthly_yield:.0f} Units (kWh)")
                c2.metric("Annual Bill Savings", f"₹{annual_savings:,.0f}")
                c3.metric("Bill Offset", f"{(monthly_yield / (monthly_bill/electricity_rate) * 100):.1f}%")

                st.subheader("🌍 Your Environmental Contribution")
                e1, e2 = st.columns(2)
                # 0.7 kg CO2 per kWh is typical for Indian Grid
                co2_saved = (annual_yield * 0.7) / 1000 
                e1.metric("CO2 Emissions Saved", f"{co2_saved:.2f} Tonnes/Year")
                e2.metric("Equivalent Trees Planted", f"{int(co2_saved * 45)} Trees")
                
                st.info("💡 **Vendor Tip:** A 5kW system in Maharashtra usually pays for itself in 4-5 years.")

            # --- TAB 2: MONTHLY AVERAGES ---
            with tab_monthly:
                st.subheader("Average Generation by Month")
                df['Month'] = df['Timestamp'].dt.strftime('%b')
                monthly_df = df.groupby(df['Timestamp'].dt.month).agg({
                    'production': 'sum',
                    'Month': 'first'
                }).sort_index()
                
                fig_monthly = px.bar(monthly_df, x='Month', y='production', 
                                    labels={'production': 'Generation (kWh)'},
                                    color_discrete_sequence=['#FFD700'])
                st.plotly_chart(fig_monthly, use_container_width=True)
                st.caption("This chart shows the typical seasonal dip during monsoon (Jun-Sept) in India.")

            # --- TAB 3: HOURLY DETAIL ---
            with tab_hourly:
                st.subheader("Historical Hourly Production")
                st.write("Select a date range to see exactly how your panels perform throughout the day.")
                
                date_range = st.date_input("Select Dates", [datetime(2023, 4, 1), datetime(2023, 4, 7)])
                if len(date_range) == 2:
                    mask = (df['Timestamp'].dt.date >= date_range[0]) & (df['Timestamp'].dt.date <= date_range[1])
                    filtered_df = df.loc[mask]
                    fig_hourly = px.area(filtered_df, x='Timestamp', y='production', 
                                        title="Power Output (kW) Over Time",
                                        color_discrete_sequence=['#FF8C00'])
                    st.plotly_chart(fig_hourly, use_container_width=True)
                
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button("Download Full Data (CSV)", csv, "solar_data.csv", "text/csv")

            # --- TAB 4: ROOFTOP AREA ---
            with tab_area:
                st.subheader("📏 Estimate Rooftop Area")
                st.write("Draw a polygon around your rooftop on the map to estimate its area.")
                
                # Create a map centered on the location
                m = folium.Map(location=[lat, lon], zoom_start=19, max_zoom=21)
                
                # Add satellite imagery
                folium.TileLayer(
                    tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
                    attr='Esri',
                    name='Esri Satellite',
                    overlay=False,
                    control=True
                ).add_to(m)
                
                # Add drawing controls
                draw = Draw(
                    export=False,
                    position='topleft',
                    draw_options={'polyline': False, 'rectangle': True, 'circle': False, 'marker': False, 'circlemarker': False, 'polygon': True},
                    edit_options={'poly': {'allowIntersection': False}}
                )
                draw.add_to(m)
                
                # Display map
                output = st_folium(m, width=800, height=600)
                
                # Calculate area if a polygon is drawn
                if output['all_drawings']:
                    # Get the last drawn polygon
                    last_drawing = output['all_drawings'][-1]
                    geometry = last_drawing['geometry']
                    
                    if geometry['type'] == 'Polygon':
                        area_sqm = calculate_geodesic_area(geometry)
                        area_sqft = area_sqm * 10.7639
                        
                        st.success(f"**Estimated Area:** {area_sqm:.2f} m² ({area_sqft:.2f} sq ft)")
                        
                        # Optional: Estimate capacity based on area
                        # Rule of thumb: 1 kW requires ~10 sq meters (approx 100 sq ft)
                        est_capacity = area_sqm / 10
                        st.info(f"Potential System Capacity: ~{est_capacity:.2f} kW")
                    else:
                        st.warning("Please draw a polygon or rectangle.")

            # --- TAB 5: GUIDE ---
            with tab_guide:
                st.markdown("""
                ### Self-Assessment Guide
                1. **Units (kWh):** This is the measure of electricity used by your home. One 'unit' on your bill is 1 kWh.
                2. **System Efficiency:** We assume a **78% Efficiency**. This accounts for heat in Indian summers, dust on panels, and the conversion from DC to AC.
                3. **Calculation:"
                   - We pull historical satellite data for your specific Latitude/Longitude.
                   - We multiply the sun's intensity (GHI) by your system siz
                   - We subtract losses for a realistic estimate.
                
                **Note:** This is a remote assessment. A physical site visit is required to check for roof shadows and structural integrity.
                """)
    else:
        st.error("Address not found. Please try adding city and state or enable manual lat/lon.")
else:
    st.info("Enter your address in the sidebar to start your solar assessment.")
