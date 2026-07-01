import { SkeletonRows, SkeletonStats } from "@/components/loading-state";

export default function Loading() {
  return (
    <section className="page">
      <div className="page-header">
        <div>
          <span className="skeleton-line wide" />
          <span className="skeleton-line medium" />
        </div>
      </div>
      <div className="grid cols-4">
        <SkeletonStats count={4} />
      </div>
      <div className="panel">
        <SkeletonRows count={6} />
      </div>
    </section>
  );
}
