import { Link } from 'react-router-dom';

export function Dashboard() {
  return (
    <div className="page dashboard">
      <h1>Rhino ReID</h1>
      <p className="lead">
        Manage rhino gallery, image descriptions (o4-mini), IndivAID conversion, prediction and confirmation.
      </p>
      <div className="cards">
        <Link to="/list-management" className="card">
          <h2>List management</h2>
          <p>Create high_quality / images lists, migrate identities between lists.</p>
        </Link>
        <Link to="/lists" className="card">
          <h2>Rhino list</h2>
          <p>Browse identities, upload images, edit captures and descriptions.</p>
        </Link>
        <Link to="/" className="card">
          <h2>Re-ID</h2>
          <p>Upload a set of query images, run re-identification, confirm or report.</p>
        </Link>
        <Link to="/predict/single" className="card">
          <h2>Predict (single image)</h2>
          <p>One image → top-5, confirm, assign identity, add to gallery.</p>
        </Link>
      </div>
    </div>
  );
}
