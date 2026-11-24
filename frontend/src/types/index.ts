/**
 * TypeScript types matching the backend Pydantic schemas exactly.
 * Keep this file in sync with backend/app/schemas/
 */

// ── Information status ──────────────────────────────────────────────────────
export type InfoStatus = 'OBSERVED' | 'CALCULATED' | 'INFERRED' | 'UNKNOWN';

export type GeometrySource = 'image_detected' | 'dimension_derived' | 'hybrid' | 'manual';
export type GeometryType = 'Rectangle' | 'Polygon' | 'IrregularPolygon';
export type SurveyFeatureType =
  | 'plot' | 'road' | 'canal' | 'river_stream' | 'railway' | 'forest'
  | 'agricultural_land' | 'open_land' | 'park_green_area' | 'building'
  | 'boundary_wall' | 'drainage' | 'water_body' | 'utility_corridor'
  | 'pathway' | 'layout_boundary' | 'north_arrow' | 'dimension_line'
  | 'survey_reference' | 'unknown_feature';

export type AnalysisStatus =
  | 'not_started'
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'partial';

export type PlotStatus = 'detected' | 'manual' | 'uncertain' | 'not_found';
export type ValidationStatus = 'valid' | 'warning' | 'error' | 'unknown';
export type ComponentStatus = 'ok' | 'running' | 'failed' | 'disabled' | 'not_implemented' | 'unavailable' | 'not_configured' | 'no_result';

// ── Evidenced value ──────────────────────────────────────────────────────────
export interface EvidencedValue<T = unknown> {
  value: T | null;
  unit: string | null;
  status: InfoStatus;
  source: string | null;
  confidence: number | null;        // 0.0–1.0 | null
  conflict: ConflictingValue[] | null;
}

export interface ConflictingValue {
  value: unknown;
  source: string;
  confidence?: number | null;
  unit?: string | null;
}

// ── Bounding box ─────────────────────────────────────────────────────────────
export interface BoundingBox {
  min_x: number;
  min_y: number;
  max_x: number;
  max_y: number;
}

// ── Geometry ─────────────────────────────────────────────────────────────────
export interface Geometry {
  geom_type: GeometryType | null;
  source: GeometrySource | null;
  confidence: number | null;
  pixel_coordinates: [number, number][] | null;
  real_world_coordinates: [number, number][] | null;
  real_world_unit: string | null;
  scale_factor_px_per_m: number | null;
  bounding_box: BoundingBox | null;
  calculated_area_m2: number | null;
  is_convex: boolean | null;
  is_closed: boolean | null;
}

// ── Measurements ─────────────────────────────────────────────────────────────
export interface Measurements {
  length_m: EvidencedValue<number> | null;
  width_m: EvidencedValue<number> | null;
  stated_area_m2: EvidencedValue<number> | null;
  calculated_area_m2: number | null;
  area_ha: number | null;
  units: string | null;
  conflicting_values: Record<string, ConflictingValue[]> | null;
}

// ── Boundaries ───────────────────────────────────────────────────────────────
export interface Boundaries {
  north: EvidencedValue<string> | null;
  south: EvidencedValue<string> | null;
  east: EvidencedValue<string> | null;
  west: EvidencedValue<string> | null;
  north_arrow_detected: boolean | null;
  north_arrow_angle_deg: number | null;
  source: string | null;
}

// ── Validation ───────────────────────────────────────────────────────────────
export interface Validation {
  status: ValidationStatus;
  warnings: string[];
  area_match: boolean | null;
  dimension_match: boolean | null;
  geometry_consistent: boolean | null;
  area_discrepancy_pct: number | null;
  details: Record<string, unknown> | null;
}

// ── Confidence ───────────────────────────────────────────────────────────────
export interface Confidence {
  overall: number | null;
  ocr: number | null;
  llm: number | null;
  opencv: number | null;
  geometry: number | null;
  validation: number | null;
  explanation: string | null;
}

// ── OCR result ───────────────────────────────────────────────────────────────
export interface OCRResult {
  id: string;
  text: string;
  confidence: number;
  bbox: [number, number, number, number];  // [x1, y1, x2, y2]
  center: [number, number];
  category: string | null;
}

// ── YOLO detection ────────────────────────────────────────────────────────────
export interface Detection {
  id: string;
  class_name: string;
  confidence: number;
  bbox: [number, number, number, number];
  center: [number, number];
  detector: string | null;
}

// ── CV candidate ─────────────────────────────────────────────────────────────
export interface CVCandidate {
  id: string;
  candidate_type: string | null;
  pixel_coordinates: [number, number][] | null;
  area_pixels: number | null;
  perimeter_pixels: number | null;
  is_convex: boolean | null;
  aspect_ratio: number | null;
  evidence_score: number | null;
  selected: boolean;
}

export interface FeatureGeometry {
  type: 'Point' | 'LineString' | 'Polygon';
  coordinates: [number, number] | [number, number][] | [number, number][][];
  coordinate_space: 'image_pixels';
}

export interface SurveyFeature {
  id: string;
  feature_type: SurveyFeatureType;
  label: string | null;
  geometry: FeatureGeometry | null;
  confidence: number | null;
  source: string;
  evidence_text: string | null;
  original_type: string | null;
  possible_types: string[];
  warning: string | null;
  review_required: boolean;
  review_status: 'detected' | 'confirmed' | 'rejected';
}

// ── Component status ──────────────────────────────────────────────────────────
export interface ComponentStatuses {
  preprocessing: ComponentStatus | null;
  ocr: ComponentStatus | null;
  llm: ComponentStatus | null;
  yolo: ComponentStatus | null;
  opencv: ComponentStatus | null;
  fusion: ComponentStatus | null;
  annotation: ComponentStatus | null;
}

// ── Plot ──────────────────────────────────────────────────────────────────────
export interface Plot {
  id: string;
  plot_number: string | null;
  survey_number: string | null;
  is_target: boolean;
  status: PlotStatus;
  confidence_overall: number | null;
  plot_number_source: string | null;
  plot_number_confidence: number | null;
  measurements: Measurements | null;
  boundaries: Boundaries | null;
  geometry: Geometry | null;
  validation: Validation | null;
}

// ── Images ────────────────────────────────────────────────────────────────────
export interface Images {
  original_url: string | null;
  annotated_url: string | null;
  preprocessed_url: string | null;
}

// ── Calibration ───────────────────────────────────────────────────────────────
export interface Calibration {
  id: string;
  status: string;
  scale_factor_px_per_m: number | null;
  confidence: number | null;
  supporting_dimensions: any[] | null;
  residual_error: number | null;
  is_manual: boolean;
}

// ── Full analysis response ────────────────────────────────────────────────────
export interface AnalysisResult {
  status: AnalysisStatus;
  document_id: string;
  document_name: string | null;
  analysis_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  message?: string | null;
  components: ComponentStatuses | null;
  component_diagnostics: Record<string, string>;
  plots: Plot[];
  ocr_results: OCRResult[];
  detections: Detection[];
  cv_candidates: CVCandidate[];
  features: SurveyFeature[];
  confidence: Confidence;
  images: Images;
  calibration: Calibration | null;
  llm_raw_response: string | null;
}

// ── Upload response ───────────────────────────────────────────────────────────
export interface UploadResponse {
  document_id: string;
  message: string;
  filename: string;
  file_size: number;
  status: string;
}

// ── Analysis trigger ──────────────────────────────────────────────────────────
export interface TriggerResponse {
  document_id: string;
  analysis_id: string;
  status: string;
  message: string;
}

// ── Geometry correction ───────────────────────────────────────────────────────
export interface GeometryCorrectionRequest {
  real_world_coordinates?: [number, number][];
  pixel_coordinates?: [number, number][];
  real_world_unit?: string | null;
  note?: string;
}

export interface GeometryCorrectionResponse {
  plot_id: string;
  geometry: Geometry;
  recalculated_area_m2: number | null;
  message: string;
}

// ── Project ───────────────────────────────────────────────────────────────────
export interface Project {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
  document_count: number;
}

export interface ProjectDocument {
  id: string;
  project_id: string | null;
  original_filename: string;
  file_type: string;
  file_size: number;
  mime_type: string | null;
  safe_filename: string;
  uploaded_at: string;
  status: string;
  image_width_px: number | null;
  image_height_px: number | null;
}

export interface ProjectDetail extends Project {
  documents: ProjectDocument[];
}
