import Image from 'next/image';

export function Brand() {
  return (
    <div className="brand flex min-h-11 items-center gap-2.5">
      <Image
        className="brand-mark"
        src="/slopy-logo.jpg"
        alt=""
        width={34}
        height={34}
        unoptimized
      />
      <span className="brand-name">Slopy</span>
    </div>
  );
}
