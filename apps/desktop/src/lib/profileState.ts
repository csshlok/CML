export type DesktopProfile = {
  display_name: string;
  avatar_path: string;
};

export const PROFILE_CHANGED_EVENT = "vault:profile-changed";

export function normalizeDesktopProfile(
  profile: DesktopSetupState["profile"] | null | undefined,
): DesktopProfile {
  return {
    display_name: profile?.display_name?.trim() ?? "",
    avatar_path: profile?.avatar_path?.trim() ?? "",
  };
}

export function profileDisplayName(profile: DesktopProfile) {
  return profile.display_name.trim() || "Local profile";
}

export async function saveDesktopProfile(
  patch: Partial<DesktopProfile>,
): Promise<DesktopProfile> {
  const desktop = window.cmlDesktop;
  if (!desktop?.updateSetupState) {
    throw new Error("Profile settings are available only in the desktop app.");
  }
  const state = await desktop.updateSetupState({ profile: patch });
  const profile = normalizeDesktopProfile(state.profile);
  window.dispatchEvent(new CustomEvent<DesktopProfile>(PROFILE_CHANGED_EVENT, { detail: profile }));
  return profile;
}

export function subscribeDesktopProfile(listener: (profile: DesktopProfile) => void) {
  const onProfileChanged = (event: Event) => {
    listener(normalizeDesktopProfile((event as CustomEvent<DesktopProfile>).detail));
  };
  window.addEventListener(PROFILE_CHANGED_EVENT, onProfileChanged);
  return () => window.removeEventListener(PROFILE_CHANGED_EVENT, onProfileChanged);
}
