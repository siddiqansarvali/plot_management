import json
import math
import ezdxf
import io
from datetime import datetime, timezone
from fpdf import FPDF

from app.database.models import AnalysisResult, Plot, SurveyFeature

def _get_coordinate_mode(analysis: AnalysisResult) -> str:
    calib = analysis.calibration
    if calib and calib.status != "uncalibrated" and calib.scale_factor_px_per_m:
        return "LOCAL SURVEY SPACE - METERS"
    return "IMAGE SPACE"

def _get_export_coords(geom_or_feature, mode, calib) -> list:
    """Return a list of [x,y] coordinates appropriate for the export mode."""
    if hasattr(geom_or_feature, "real_world_coordinates_json"): # Plot Geometry
        if mode == "LOCAL SURVEY SPACE - METERS":
            coords_str = geom_or_feature.real_world_coordinates_json
            if coords_str:
                return json.loads(coords_str)
        # fallback or image space
        coords_str = geom_or_feature.pixel_coordinates_json
        if coords_str:
            return json.loads(coords_str)
        return []

    if hasattr(geom_or_feature, "geometry_json"): # SurveyFeature
        coords_str = geom_or_feature.geometry_json
        if not coords_str:
            return []
        try:
            geom_dict = json.loads(coords_str)
        except Exception:
            return []
            
        if "coordinates" not in geom_dict:
            return []
            
        coords = geom_dict["coordinates"]
        
        # Flatter it to simple list of points
        if geom_dict.get("type") == "Point":
            pts = [coords]
        elif geom_dict.get("type") == "Polygon":
            pts = coords[0] if coords else []
        elif geom_dict.get("type") == "LineString":
            pts = coords
        else:
            return []

        if mode == "LOCAL SURVEY SPACE - METERS" and calib and calib.scale_factor_px_per_m:
            ox = calib.origin_x_px or 0.0
            oy = calib.origin_y_px or 0.0
            scale = calib.scale_factor_px_per_m
            pts = [[(pt[0] - ox) / scale, -(pt[1] - oy) / scale] for pt in pts]
            
        return pts
    return []

def generate_svg(analysis: AnalysisResult) -> str:
    mode = _get_coordinate_mode(analysis)
    calib = analysis.calibration
    
    all_x = []
    all_y = []
    
    plots_data = []
    for plot in analysis.plots:
        coords = _get_export_coords(plot.geometry, mode, calib)
        if coords:
            for x, y in coords:
                all_x.append(x)
                all_y.append(y)
            plots_data.append((plot, coords))
            
    features_data = []
    for feature in analysis.features:
        if feature.review_status == "rejected":
            continue
        coords = _get_export_coords(feature, mode, calib)
        if coords:
            for x, y in coords:
                all_x.append(x)
                all_y.append(y)
            features_data.append((feature, coords))

    if not all_x:
        return '<svg xmlns="http://www.w3.org/2000/svg"><text x="10" y="20">No geometry found.</text></svg>'
        
    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)
    
    width = max(max_x - min_x, 1)
    height = max(max_y - min_y, 1)
    
    padding = max(width, height) * 0.1
    vb_x = min_x - padding
    vb_y = min_y - padding
    vb_w = width + padding * 2
    vb_h = height + padding * 2

    font_size = max(width, height) * 0.02

    svg = f'<?xml version="1.0" encoding="UTF-8"?>\n'
    svg += f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb_x} {vb_y} {vb_w} {vb_h}">\n'
    svg += f'    <desc>\n        Survey ID: {analysis.id}\n        Coordinate Mode: {mode}\n    </desc>\n'
    svg += f'    <rect width="100%" height="100%" fill="#ffffff"/>\n'

    # Draw features (e.g. roads, etc)
    for feature, coords in features_data:
        if len(coords) >= 2:
            pts_str = " ".join([f"{pt[0]},{pt[1]}" for pt in coords])
            color = "#e2e8f0" if feature.feature_type == "road" else "#f1f5f9"
            if len(coords) > 2:
                svg += f'    <polygon points="{pts_str}" fill="{color}" stroke="#94a3b8" stroke-width="{font_size * 0.1}"/>\n'
            else:
                svg += f'    <polyline points="{pts_str}" fill="none" stroke="#94a3b8" stroke-width="{font_size * 0.3}"/>\n'
        
        # Label
        cx = sum(p[0] for p in coords) / len(coords)
        cy = sum(p[1] for p in coords) / len(coords)
        svg += f'    <text x="{cx}" y="{cy}" text-anchor="middle" font-family="sans-serif" font-size="{font_size*0.8}" fill="#475569">{feature.label or feature.feature_type}</text>\n'

    # Draw plots
    for plot, coords in plots_data:
        if len(coords) < 3:
            continue
        pts_str = " ".join([f"{pt[0]},{pt[1]}" for pt in coords])
        svg += f'    <polygon points="{pts_str}" fill="none" stroke="#1d4ed8" stroke-width="{font_size * 0.15}"/>\n'
        
        cx = sum(p[0] for p in coords) / len(coords)
        cy = sum(p[1] for p in coords) / len(coords)
        
        svg += f'    <text x="{cx}" y="{cy}" text-anchor="middle" font-family="sans-serif" font-size="{font_size}" font-weight="bold" fill="#0f172a">PLOT {plot.plot_number or ""}</text>\n'
        
        if plot.measurements:
            dims = []
            if plot.measurements.length_m: dims.append(str(plot.measurements.length_m))
            if plot.measurements.width_m: dims.append(str(plot.measurements.width_m))
            if dims:
                dim_str = " x ".join(dims) + (f" m" if mode != "IMAGE SPACE" else " units")
                svg += f'    <text x="{cx}" y="{cy + font_size * 1.2}" text-anchor="middle" font-family="sans-serif" font-size="{font_size * 0.6}" fill="#334155">{dim_str}</text>\n'

    # North arrow
    north_arrow_angle = None
    for plot in analysis.plots:
        if plot.boundaries and plot.boundaries.north_arrow_detected and plot.boundaries.north_arrow_angle_deg is not None:
            north_arrow_angle = plot.boundaries.north_arrow_angle_deg
            break
            
    if north_arrow_angle is not None:
        nx = max_x - padding * 0.5
        ny = min_y + padding * 0.5
        arrow_len = font_size * 3
        svg += f'    <g transform="translate({nx}, {ny}) rotate({north_arrow_angle})">\n'
        svg += f'        <line x1="0" y1="{arrow_len}" x2="0" y2="-{arrow_len}" stroke="#ef4444" stroke-width="{font_size*0.2}"/>\n'
        svg += f'        <polygon points="-{font_size*0.5},-{arrow_len*0.6} 0,-{arrow_len} {font_size*0.5},-{arrow_len*0.6}" fill="#ef4444"/>\n'
        svg += f'        <text x="0" y="-{arrow_len*1.2}" text-anchor="middle" font-family="sans-serif" font-size="{font_size}" fill="#ef4444">N</text>\n'
        svg += f'    </g>\n'

    # Metadata corner
    svg += f'    <text x="{min_x}" y="{max_y + padding*0.6}" font-family="sans-serif" font-size="{font_size}" fill="#0f172a">PLOTLINE DIGITAL SURVEY</text>\n'
    svg += f'    <text x="{min_x}" y="{max_y + padding*0.6 + font_size*1.5}" font-family="sans-serif" font-size="{font_size*0.7}" fill="#475569">Coordinate Mode: {mode}</text>\n'
    if mode == "LOCAL SURVEY SPACE - METERS":
        svg += f'    <text x="{min_x}" y="{max_y + padding*0.6 + font_size*3}" font-family="sans-serif" font-size="{font_size*0.7}" fill="#475569">Scale: 1 unit = 1 meter</text>\n'

    svg += '</svg>'
    return svg

def generate_pdf(analysis: AnalysisResult) -> bytes:
    mode = _get_coordinate_mode(analysis)
    calib = analysis.calibration
    
    pdf = FPDF(orientation="landscape", unit="mm", format="A4")
    pdf.add_page()
    
    pdf.set_font("helvetica", "B", 14)
    pdf.cell(0, 8, "PLOTLINE - DIGITAL SURVEY RECONSTRUCTION", align="C")
    pdf.ln(10)
    
    # Metadata
    pdf.set_font("helvetica", "", 9)
    pdf.cell(100, 5, f"Survey ID: {analysis.id}")
    pdf.cell(100, 5, f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    pdf.ln(5)
    pdf.cell(100, 5, f"Coordinate Mode: {mode}")
    if mode == "LOCAL SURVEY SPACE - METERS":
        pdf.cell(100, 5, "Scale: Metric (Meters)")
    pdf.ln(10)

    # Draw the Digital Redraw on the PDF
    draw_x, draw_y, draw_w, draw_h = 20, 35, 250, 140
    pdf.rect(draw_x, draw_y, draw_w, draw_h)
    
    all_x, all_y = [], []
    plots_data = []
    for plot in analysis.plots:
        coords = _get_export_coords(plot.geometry, mode, calib)
        if coords and len(coords) >= 3:
            all_x.extend([p[0] for p in coords])
            all_y.extend([p[1] for p in coords])
            plots_data.append((plot, coords))
            
    features_data = []
    for feature in analysis.features:
        if feature.review_status == "rejected":
            continue
        coords = _get_export_coords(feature, mode, calib)
        if coords:
            all_x.extend([p[0] for p in coords])
            all_y.extend([p[1] for p in coords])
            features_data.append((feature, coords))

    if all_x and all_y:
        min_x, max_x = min(all_x), max(all_x)
        min_y, max_y = min(all_y), max(all_y)
        
        w = max(max_x - min_x, 1)
        h = max(max_y - min_y, 1)
        
        scale = min((draw_w - 20) / w, (draw_h - 20) / h)
        off_x = draw_x + 10 + ((draw_w - 20) - (w * scale)) / 2
        off_y = draw_y + 10 + ((draw_h - 20) - (h * scale)) / 2
        
        def px(x): return off_x + (x - min_x) * scale
        def py(y): return off_y + (y - min_y) * scale

        pdf.set_draw_color(148, 163, 184) # slate-400
        for feature, coords in features_data:
            if len(coords) > 2:
                pdf.set_fill_color(241, 245, 249) # slate-100
                if feature.feature_type == 'road':
                    pdf.set_fill_color(226, 232, 240) # slate-200
                pts = [(px(pt[0]), py(pt[1])) for pt in coords]
                pdf.polygon(pts, style="DF")
            elif len(coords) == 2:
                pdf.line(px(coords[0][0]), py(coords[0][1]), px(coords[1][0]), py(coords[1][1]))
                
            cx = sum(p[0] for p in coords) / len(coords)
            cy = sum(p[1] for p in coords) / len(coords)
            pdf.set_text_color(71, 85, 105)
            pdf.set_font("helvetica", "", 7)
            label = str(feature.label or feature.feature_type)
            pdf.text(px(cx) - pdf.get_string_width(label)/2, py(cy), label)
            
        pdf.set_draw_color(29, 78, 216) # blue-700
        pdf.set_text_color(15, 23, 42) # slate-900
        for plot, coords in plots_data:
            pts = [(px(pt[0]), py(pt[1])) for pt in coords]
            pdf.polygon(pts, style="D")
            
            cx = sum(p[0] for p in coords) / len(coords)
            cy = sum(p[1] for p in coords) / len(coords)
            
            pdf.set_font("helvetica", "B", 8)
            t = f"PLOT {plot.plot_number or ''}"
            pdf.text(px(cx) - pdf.get_string_width(t)/2, py(cy), t)
            
            if plot.measurements:
                dims = []
                if plot.measurements.length_m: dims.append(str(plot.measurements.length_m))
                if plot.measurements.width_m: dims.append(str(plot.measurements.width_m))
                if dims:
                    dim_str = " x ".join(dims) + (f" m" if mode != "IMAGE SPACE" else " units")
                    pdf.set_font("helvetica", "", 6)
                    pdf.text(px(cx) - pdf.get_string_width(dim_str)/2, py(cy) + 3, dim_str)
                    
        north_arrow_angle = None
        for plot in analysis.plots:
            if plot.boundaries and plot.boundaries.north_arrow_detected and plot.boundaries.north_arrow_angle_deg is not None:
                north_arrow_angle = plot.boundaries.north_arrow_angle_deg
                break
        if north_arrow_angle is not None:
            nx = draw_x + draw_w - 15
            ny = draw_y + 15
            pdf.set_text_color(239, 68, 68)
            pdf.set_font("helvetica", "B", 10)
            pdf.text(nx, ny, "N ^")

    pdf.ln(145)
    
    pdf.set_font("helvetica", "B", 10)
    pdf.cell(0, 6, "Validation & Review Status", ln=1)
    
    pdf.set_font("helvetica", "", 8)
    manual_plots = sum(1 for p in analysis.plots if p.status == 'manual')
    error_plots = sum(1 for p in analysis.plots if p.validation and p.validation.status == 'error')
    pdf.cell(0, 5, f"Total Plots: {len(analysis.plots)} | Manually Corrected: {manual_plots} | Validation Errors: {error_plots}", ln=1)

    return bytes(pdf.output(dest="S"))

def generate_geojson(analysis: AnalysisResult) -> dict:
    mode = _get_coordinate_mode(analysis)
    calib = analysis.calibration
    features = []
    
    for plot in analysis.plots:
        coords = _get_export_coords(plot.geometry, mode, calib)
        if coords and len(coords) >= 3:
            closed = coords + [coords[0]] if coords[0] != coords[-1] else coords
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [closed]
                },
                "properties": {
                    "feature_class": "PLOT",
                    "plot_number": plot.plot_number,
                    "stated_area": plot.measurements.stated_area_m2 if plot.measurements else None,
                    "calculated_area": plot.geometry.calculated_area_m2 if plot.geometry else None,
                    "status": plot.status,
                    "review_status": "MANUALLY_CORRECTED" if plot.status == "manual" else ("CONFIRMED" if plot.status == "detected" else "REVIEW_REQUIRED")
                }
            })
            
    for feature in analysis.features:
        if feature.review_status == "rejected":
            continue
        coords = _get_export_coords(feature, mode, calib)
        if coords:
            geom_type = "Point"
            if feature.geometry_json:
                try:
                    gdict = json.loads(feature.geometry_json)
                    geom_type = gdict.get("type", "Point")
                except:
                    pass
            
            if geom_type == "Polygon" and len(coords) >= 3:
                closed = coords + [coords[0]] if coords[0] != coords[-1] else coords
                geom_obj = {"type": "Polygon", "coordinates": [closed]}
            elif geom_type == "LineString" and len(coords) >= 2:
                geom_obj = {"type": "LineString", "coordinates": coords}
            else:
                geom_obj = {"type": "Point", "coordinates": coords[0]}
                
            features.append({
                "type": "Feature",
                "geometry": geom_obj,
                "properties": {
                    "feature_class": str(feature.feature_type).upper(),
                    "label": feature.label,
                    "review_status": str(feature.review_status).upper()
                }
            })
            
    return {
        "type": "FeatureCollection",
        "metadata": {
            "coordinate_mode": mode,
            "survey_id": analysis.id,
            "revision": len(analysis.plots[0].corrections) if analysis.plots and analysis.plots[0].corrections else 0
        },
        "features": features
    }

def generate_dxf(analysis: AnalysisResult) -> bytes:
    mode = _get_coordinate_mode(analysis)
    calib = analysis.calibration
    doc = ezdxf.new('R2010')
    if mode == "LOCAL SURVEY SPACE - METERS":
        doc.header['$INSUNITS'] = 6  # Meters
        
    doc.layers.add("PLOTS", color=5)  # Blue
    doc.layers.add("ROADS", color=2)  # Yellow
    doc.layers.add("LABELS", color=7) # White/Black
    doc.layers.add("DIMENSIONS", color=3)
    doc.layers.add("NORTH_ARROW", color=1) # Red
    
    msp = doc.modelspace()
    
    for plot in analysis.plots:
        coords = _get_export_coords(plot.geometry, mode, calib)
        if coords and len(coords) >= 3:
            msp.add_lwpolyline(coords, dxfattribs={'layer': 'PLOTS', 'closed': True})
            cx = sum(p[0] for p in coords) / len(coords)
            cy = sum(p[1] for p in coords) / len(coords)
            height = max(0.5, (max(p[0] for p in coords)-min(p[0] for p in coords))*0.05)
            msp.add_text(f"PLOT {plot.plot_number or ''}", dxfattribs={
                'layer': 'LABELS', 'height': height
            }).set_placement((cx, cy), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
            
            if plot.measurements:
                dims = []
                if plot.measurements.length_m: dims.append(str(plot.measurements.length_m))
                if plot.measurements.width_m: dims.append(str(plot.measurements.width_m))
                if dims:
                    dim_str = " x ".join(dims) + (f" m" if mode != "IMAGE SPACE" else "")
                    msp.add_text(dim_str, dxfattribs={
                        'layer': 'DIMENSIONS', 'height': height * 0.6
                    }).set_placement((cx, cy - height*1.2), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
            
    for feature in analysis.features:
        if feature.review_status == "rejected":
            continue
        coords = _get_export_coords(feature, mode, calib)
        if coords:
            layer_name = "ROADS" if feature.feature_type == "road" else str(feature.feature_type).upper()
            if layer_name not in doc.layers:
                doc.layers.add(layer_name, color=3)
                
            geom_type = "Point"
            if feature.geometry_json:
                try:
                    gdict = json.loads(feature.geometry_json)
                    geom_type = gdict.get("type", "Point")
                except:
                    pass
            
            if geom_type == "Polygon" and len(coords) >= 3:
                msp.add_lwpolyline(coords, dxfattribs={'layer': layer_name, 'closed': True})
            elif geom_type == "LineString" and len(coords) >= 2:
                msp.add_lwpolyline(coords, dxfattribs={'layer': layer_name, 'closed': False})
            
            cx = sum(p[0] for p in coords) / len(coords)
            cy = sum(p[1] for p in coords) / len(coords)
            
            height = 1.0
            if len(coords) >= 2:
                height = max(0.5, (max(p[0] for p in coords)-min(p[0] for p in coords))*0.05)
            
            msp.add_text(str(feature.label or feature.feature_type), dxfattribs={
                'layer': 'LABELS', 'height': height
            }).set_placement((cx, cy), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
            
    north_arrow_angle = None
    for plot in analysis.plots:
        if plot.boundaries and plot.boundaries.north_arrow_detected and plot.boundaries.north_arrow_angle_deg is not None:
            north_arrow_angle = plot.boundaries.north_arrow_angle_deg
            break
    if north_arrow_angle is not None:
        msp.add_text(f"N (Angle: {north_arrow_angle} deg)", dxfattribs={
            'layer': 'NORTH_ARROW', 'height': 2.0
        }).set_placement((0, 0), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)

    out = io.StringIO()
    doc.write(out)
    return out.getvalue().encode('utf-8')
