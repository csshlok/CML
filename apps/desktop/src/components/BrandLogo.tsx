type BrandLogoProps = {
  className?: string;
  alt?: string;
};

export const VAULT_SIDEBAR_WORDMARK = "/brand/Frame%208.png";
export const VAULT_OPENING_WORDMARK = VAULT_SIDEBAR_WORDMARK;

export function BrandLogo({
  className = "",
  alt = "Vault",
}: BrandLogoProps) {
  return (
    <span className={`vault-brand-logo ${className}`} role="img" aria-label={alt}>
      <span className="vault-brand-art" aria-hidden="true" />
    </span>
  );
}

export function SidebarBrandLogo({
  className = "",
  alt = "Vault",
}: BrandLogoProps) {
  return (
    <span className={`vault-sidebar-wordmark ${className}`}>
      <span className="vault-brand-art" role="img" aria-label={alt} />
    </span>
  );
}
