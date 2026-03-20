export const API = '/api/v1';

export const TYPE_LABELS = {
  choice: '\u55AE\u9078', truefalse: '\u662F\u975E', multichoice: '\u8907\u9078',
  scenario_choice: '\u60C5\u5883\u55AE\u9078', scenario_multichoice: '\u60C5\u5883\u8907\u9078',
};

export const TYPE_BADGE_CLASS = {
  choice: 'badge-choice', truefalse: 'badge-tf', multichoice: 'badge-mc',
  scenario_choice: 'badge-scenario', scenario_multichoice: 'badge-scenario',
};

export function isMultichoice(type) {
  return type === 'multichoice' || type === 'scenario_multichoice';
}

export function escapeHtml(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}
