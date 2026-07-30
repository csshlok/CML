export const settingsSectionIds = [
  "profile",
  "library",
  "models",
  "connections",
  "health",
  "advanced",
] as const;

export type SettingsSectionId = (typeof settingsSectionIds)[number];

const settingsAliases: Record<string, SettingsSectionId> = {
  storage: "library",
  privacy: "library",
  embeddings: "models",
  ocr: "models",
  odin: "connections",
  diagnostics: "advanced",
};

export function canonicalSettingsSection(value?: string): SettingsSectionId {
  const candidate = value ? settingsAliases[value] ?? value : "profile";
  return settingsSectionIds.includes(candidate as SettingsSectionId)
    ? (candidate as SettingsSectionId)
    : "profile";
}

export function settingsNoticeIsError(message: string): boolean {
  return /\b(could not|failed|failure|invalid|unavailable|incorrect|error)\b/i.test(
    message,
  );
}
