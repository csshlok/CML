type BrandLogoProps = {
  className?: string;
  alt?: string;
};

export const VAULT_OPENING_WORDMARK = "/brand/Container.svg";
export const VAULT_SIDEBAR_WORDMARK = "/brand/Frame%208.png";

export function BrandLogo({
  className = "",
  alt = "Vault",
}: BrandLogoProps) {
  return (
    <img
      src={VAULT_OPENING_WORDMARK}
      alt={alt}
      className={className}
      draggable={false}
    />
  );
}

export function SidebarBrandLogo({
  className = "",
  alt = "Vault",
}: BrandLogoProps) {
  return (
    <span className={`vault-sidebar-wordmark ${className}`}>
      <img
        src={VAULT_SIDEBAR_WORDMARK}
        alt={alt}
        draggable={false}
      />
    </span>
  );
}
