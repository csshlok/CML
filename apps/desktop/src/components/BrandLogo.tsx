type BrandLogoProps = {
  className?: string;
  alt?: string;
};

export const VAULT_OPENING_WORDMARK = "/brand/Container.svg";

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
