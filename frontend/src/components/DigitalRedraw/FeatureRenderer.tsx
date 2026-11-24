import type { FeatureGeometry, SurveyFeature, SurveyFeatureType } from '../../types';
import { featureTypeLabel } from './featureTypes';

type Point = [number, number];

const COLORS: Record<SurveyFeatureType, string> = {
  plot: '#2563eb', road: '#4b5563', canal: '#0284c7', river_stream: '#0284c7',
  railway: '#475569', forest: '#15803d', agricultural_land: '#65a30d',
  open_land: '#78716c', park_green_area: '#16a34a', building: '#7c3aed',
  boundary_wall: '#334155', drainage: '#0891b2', water_body: '#0e7490',
  utility_corridor: '#9333ea', pathway: '#78716c', layout_boundary: '#b45309',
  north_arrow: '#0f172a', dimension_line: '#64748b', survey_reference: '#a16207',
  unknown_feature: '#d97706',
};

const ABBREVIATIONS: Record<SurveyFeatureType, string> = {
  plot: 'P', road: 'R', canal: 'C', river_stream: '≈', railway: 'RR',
  forest: 'F', agricultural_land: 'AG', open_land: 'O', park_green_area: 'G',
  building: 'B', boundary_wall: 'W', drainage: 'D', water_body: 'H',
  utility_corridor: 'U', pathway: 'A', layout_boundary: 'L', north_arrow: 'N',
  dimension_line: '↔', survey_reference: 'S', unknown_feature: '?',
};

const PATTERNED_TYPES = new Set<SurveyFeatureType>([
  'road', 'canal', 'river_stream', 'railway', 'forest', 'agricultural_land',
  'open_land', 'park_green_area', 'building', 'drainage', 'water_body',
  'pathway', 'utility_corridor',
]);

function linesForGeometry(geometry: FeatureGeometry): Point[][] {
  if (geometry.type === 'Point') return [[geometry.coordinates as Point]];
  if (geometry.type === 'LineString') return [geometry.coordinates as Point[]];
  return geometry.coordinates as Point[][];
}

function pathFor(points: Point[]): string {
  return points.map(([x, y], index) => `${index === 0 ? 'M' : 'L'} ${x} ${y}`).join(' ');
}

export interface FeatureRendererProps {
  feature: SurveyFeature;
  markerSize: number;
  selected: boolean;
  onSelect: (id: string) => void;
  onDragStart?: (id: string, event: React.PointerEvent<SVGGElement>) => void;
}

export default function FeatureRenderer({ feature, markerSize, selected, onSelect, onDragStart }: FeatureRendererProps) {
  const geometry = feature.geometry;
  if (!geometry || geometry.coordinate_space !== 'image_pixels') return null;
  const color = COLORS[feature.feature_type];
  const label = feature.label || featureTypeLabel(feature.feature_type).toUpperCase();
  const mark = ABBREVIATIONS[feature.feature_type];

  if (geometry.type === 'Point') {
    const [x, y] = geometry.coordinates as Point;
    if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
    const radius = markerSize * 0.72;
    return (
      <g
        className="redraw-feature redraw-feature-point"
        onClick={event => { event.stopPropagation(); onSelect(feature.id); }}
        onPointerDown={event => {
          event.stopPropagation();
          onSelect(feature.id);
          if (selected && onDragStart) onDragStart(feature.id, event);
        }}
        style={{ cursor: selected ? 'move' : 'pointer' }}
      >
        <circle cx={x} cy={y} r={radius} fill={feature.review_required ? '#fff7ed' : '#ffffff'} stroke={color} strokeWidth={markerSize * 0.17} strokeDasharray={feature.review_required ? `${markerSize * 0.25} ${markerSize * 0.18}` : undefined} />
        <text x={x} y={y + markerSize * 0.16} textAnchor="middle" fontSize={markerSize * 0.68} fontWeight="700" fill={color}>{mark}</text>
        <text x={x + radius + markerSize * 0.32} y={y - markerSize * 0.2} fontSize={markerSize * 0.88} fontWeight="600" fill="#1f2937" stroke="#fff" strokeWidth={markerSize * 0.13} paintOrder="stroke">{label}</text>
        {selected && <circle cx={x} cy={y} r={radius * 1.55} fill="none" stroke="#f97316" strokeWidth={markerSize * 0.12} />}
      </g>
    );
  }

  const lines = linesForGeometry(geometry);
  return (
    <g
      className="redraw-feature redraw-feature-extent"
      onClick={event => { event.stopPropagation(); onSelect(feature.id); }}
      style={{ cursor: 'pointer' }}
      opacity={feature.review_required ? 0.74 : 1}
    >
      {geometry.type === 'Polygon' ? lines.map((ring, index) => (
        <polygon
          key={index}
          points={ring.map(([x, y]) => `${x},${y}`).join(' ')}
          fill={feature.feature_type === 'plot' ? '#eff6ff' : PATTERNED_TYPES.has(feature.feature_type) ? `url(#feature-pattern-${feature.feature_type})` : 'none'}
          stroke={selected ? '#f97316' : color}
          strokeWidth={markerSize * 0.16}
          strokeDasharray={feature.feature_type === 'layout_boundary' ? `${markerSize} ${markerSize * 0.55}` : undefined}
        />
      )) : lines.map((points, index) => {
        const path = pathFor(points);
        if (feature.feature_type === 'road') return <g key={index}>
          <path d={path} fill="none" stroke={selected ? '#f97316' : color} strokeWidth={markerSize * 1.2} strokeLinecap="round" />
          <path d={path} fill="none" stroke="#f8fafc" strokeWidth={markerSize * 0.12} strokeDasharray={`${markerSize * 0.7} ${markerSize * 0.55}`} />
        </g>;
        if (feature.feature_type === 'railway') return <g key={index}>
          <path d={path} fill="none" stroke={selected ? '#f97316' : color} strokeWidth={markerSize * 0.12} />
          <path d={path} fill="none" stroke={color} strokeWidth={markerSize * 0.26} strokeDasharray={`${markerSize * 0.14} ${markerSize * 0.42}`} />
        </g>;
        const water = ['canal', 'river_stream', 'water_body'].includes(feature.feature_type);
        return <path key={index} d={path} fill="none" stroke={selected ? '#f97316' : color} strokeWidth={markerSize * 0.24} strokeDasharray={water ? `${markerSize * 0.42} ${markerSize * 0.3}` : undefined} strokeLinecap="round" />;
      })}
      {lines[0]?.[0] && <text x={lines[0][0][0] + markerSize * 0.3} y={lines[0][0][1] - markerSize * 0.3} fontSize={markerSize * 0.85} fontWeight="600" fill="#1f2937" stroke="#fff" strokeWidth={markerSize * 0.13} paintOrder="stroke">{label}</text>}
    </g>
  );
}

export function FeaturePatterns() {
  return (
    <defs>
      <pattern id="feature-pattern-forest" width="18" height="18" patternUnits="userSpaceOnUse">
        <circle cx="5" cy="6" r="3" fill="#86efac" stroke="#15803d" strokeWidth="1" />
        <circle cx="14" cy="14" r="3" fill="#bbf7d0" stroke="#15803d" strokeWidth="1" />
      </pattern>
      <pattern id="feature-pattern-agricultural_land" width="14" height="14" patternUnits="userSpaceOnUse" patternTransform="rotate(28)">
        <path d="M 0 0 V 14 M 6 0 V 14" stroke="#65a30d" strokeWidth="1.2" />
      </pattern>
      <pattern id="feature-pattern-park_green_area" width="16" height="16" patternUnits="userSpaceOnUse">
        <path d="M8 3 C4 5 4 9 8 11 C12 9 12 5 8 3 M8 10 V14" fill="none" stroke="#16a34a" strokeWidth="1.2" />
      </pattern>
      <pattern id="feature-pattern-water_body" width="20" height="12" patternUnits="userSpaceOnUse">
        <path d="M0 4 Q5 0 10 4 T20 4 M0 10 Q5 6 10 10 T20 10" fill="none" stroke="#38bdf8" strokeWidth="1" />
      </pattern>
      <pattern id="feature-pattern-canal" width="20" height="12" patternUnits="userSpaceOnUse">
        <path d="M0 4 Q5 0 10 4 T20 4 M0 10 Q5 6 10 10 T20 10" fill="none" stroke="#0284c7" strokeWidth="1.2" />
      </pattern>
      <pattern id="feature-pattern-river_stream" width="20" height="12" patternUnits="userSpaceOnUse">
        <path d="M0 4 Q5 0 10 4 T20 4 M0 10 Q5 6 10 10 T20 10" fill="none" stroke="#0e7490" strokeWidth="1.2" />
      </pattern>
      <pattern id="feature-pattern-road" width="16" height="16" patternUnits="userSpaceOnUse">
        <path d="M0 8 H16" stroke="#d1d5db" strokeWidth="2" strokeDasharray="5 4" />
      </pattern>
      <pattern id="feature-pattern-railway" width="16" height="16" patternUnits="userSpaceOnUse">
        <path d="M0 8 H16 M4 4 V12 M12 4 V12" stroke="#475569" strokeWidth="1.4" />
      </pattern>
      <pattern id="feature-pattern-building" width="12" height="12" patternUnits="userSpaceOnUse">
        <path d="M-3 3 L3 -3 M0 12 L12 0 M9 15 L15 9" stroke="#a78bfa" strokeWidth="1" />
      </pattern>
      <pattern id="feature-pattern-open_land" width="16" height="16" patternUnits="userSpaceOnUse">
        <circle cx="3" cy="3" r="0.8" fill="#a8a29e" />
      </pattern>
      <pattern id="feature-pattern-drainage" width="14" height="14" patternUnits="userSpaceOnUse">
        <path d="M0 7 H14" stroke="#0891b2" strokeWidth="1" strokeDasharray="3 2" />
      </pattern>
      <pattern id="feature-pattern-pathway" width="14" height="14" patternUnits="userSpaceOnUse">
        <path d="M0 7 H14" stroke="#78716c" strokeWidth="1" strokeDasharray="2 3" />
      </pattern>
      <pattern id="feature-pattern-utility_corridor" width="14" height="14" patternUnits="userSpaceOnUse">
        <path d="M0 7 H14" stroke="#9333ea" strokeWidth="1.2" strokeDasharray="5 2 1 2" />
      </pattern>
    </defs>
  );
}
