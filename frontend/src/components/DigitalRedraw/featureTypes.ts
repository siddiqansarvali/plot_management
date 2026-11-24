import type { SurveyFeatureType } from '../../types';

export function featureTypeLabel(type: SurveyFeatureType): string {
  return type.replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase());
}
