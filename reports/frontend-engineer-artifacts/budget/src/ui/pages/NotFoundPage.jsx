import React from 'react';
import { Link } from 'react-router-dom';

export default function NotFoundPage() {
  return (
    <section className="panel" aria-labelledby="nf-title">
      <div className="panel-hd">
        <h1 id="nf-title" style={{ margin: 0 }}>Not found</h1>
      </div>
      <div className="panel-bd stack">
        <p>The page you’re looking for doesn’t exist.</p>
        <Link className="btn" to="/">Go to dashboard</Link>
      </div>
    </section>
  );
}
