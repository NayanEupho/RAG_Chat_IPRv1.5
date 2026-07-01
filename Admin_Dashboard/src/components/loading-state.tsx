export function SkeletonRows({ count = 4 }: { count?: number }) {
  return (
    <>
      {Array.from({ length: count }).map((_, index) => (
        <div className="stack-row row-main" key={index}>
          <span>
            <span className="skeleton-line wide" />
            <span className="skeleton-line medium" />
          </span>
          <span className="skeleton-pill" />
        </div>
      ))}
    </>
  );
}

export function SkeletonStats({ count = 4 }: { count?: number }) {
  return (
    <>
      {Array.from({ length: count }).map((_, index) => (
        <div className="stat" key={index}>
          <span className="skeleton-line medium" />
          <strong className="skeleton-number" />
        </div>
      ))}
    </>
  );
}
