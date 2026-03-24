import { useState, useEffect } from 'react';
import { lists as listsApi } from '../api';

type List = { id: number; name: string; list_type: string; source_path: string | null };
type Identity = { id: number; name: string; pid: number | null };

export function Lists() {
  const [lists, setLists] = useState<List[]>([]);
  const [selectedList, setSelectedList] = useState<List | null>(null);
  const [identities, setIdentities] = useState<Identity[]>([]);
  const [newListName, setNewListName] = useState('');
  const [newListType, setNewListType] = useState<'high_quality' | 'images'>('high_quality');
  const [newIdentityName, setNewIdentityName] = useState('');
  const [migrateFrom, setMigrateFrom] = useState<number | null>(null);
  const [migrateTo, setMigrateTo] = useState<number | null>(null);

  const loadLists = () => listsApi.getAll().then((r) => setLists(r.data));
  useEffect(() => { loadLists(); }, []);

  useEffect(() => {
    if (!selectedList) {
      setIdentities([]);
      return;
    }
    listsApi.getIdentities(selectedList.id).then((r) => setIdentities(r.data));
  }, [selectedList]);

  const createList = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newListName.trim()) return;
    await listsApi.create(newListName.trim(), newListType);
    setNewListName('');
    loadLists();
  };

  const createIdentity = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedList || !newIdentityName.trim()) return;
    await listsApi.createIdentity(selectedList.id, newIdentityName.trim());
    setNewIdentityName('');
    listsApi.getIdentities(selectedList.id).then((r) => setIdentities(r.data));
  };

  const doMigrate = async () => {
    if (migrateFrom == null || migrateTo == null) return;
    await listsApi.migrate(migrateFrom, migrateTo);
    setMigrateFrom(null);
    setMigrateTo(null);
    loadLists();
    if (selectedList?.id === migrateFrom || selectedList?.id === migrateTo) {
      listsApi.getIdentities(selectedList.id).then((r) => setIdentities(r.data));
    }
  };

  return (
    <div className="page lists-page">
      <h1>Rhino Lists</h1>

      <section className="section">
        <h2>Create list</h2>
        <form onSubmit={createList} className="form-inline">
          <input
            value={newListName}
            onChange={(e) => setNewListName(e.target.value)}
            placeholder="List name"
          />
          <select value={newListType} onChange={(e) => setNewListType(e.target.value as 'high_quality' | 'images')}>
            <option value="high_quality">high_quality</option>
            <option value="images">images</option>
          </select>
          <button type="submit">Create</button>
        </form>
      </section>

      <section className="section">
        <h2>Migrate list</h2>
        <div className="form-inline">
          <select value={migrateFrom ?? ''} onChange={(e) => setMigrateFrom(Number(e.target.value) || null)}>
            <option value="">Source</option>
            {lists.map((l) => (
              <option key={l.id} value={l.id}>{l.name} ({l.list_type})</option>
            ))}
          </select>
          <span>→</span>
          <select value={migrateTo ?? ''} onChange={(e) => setMigrateTo(Number(e.target.value) || null)}>
            <option value="">Target</option>
            {lists.map((l) => (
              <option key={l.id} value={l.id}>{l.name} ({l.list_type})</option>
            ))}
          </select>
          <button type="button" onClick={doMigrate} disabled={!migrateFrom || !migrateTo}>Migrate</button>
        </div>
      </section>

      <section className="section">
        <h2>Lists & Identity</h2>
        <div className="two-col">
          <div>
            <ul className="list-list">
              {lists.map((l) => (
                <li key={l.id}>
                  <button
                    type="button"
                    className={selectedList?.id === l.id ? 'active' : ''}
                    onClick={() => setSelectedList(l)}
                  >
                    {l.name} <span className="badge">{l.list_type}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <div>
            {selectedList && (
              <>
                <h3>{selectedList.name}</h3>
                <form onSubmit={createIdentity} className="form-inline">
                  <input
                    value={newIdentityName}
                    onChange={(e) => setNewIdentityName(e.target.value)}
                    placeholder="Identity name (e.g. Donny ID1444)"
                  />
                  <button type="submit">Add identity</button>
                </form>
                <ul className="identity-list">
                  {identities.map((i) => (
                    <li key={i.id}>{i.name} {i.pid != null && <span className="pid">pid={i.pid}</span>}</li>
                  ))}
                </ul>
              </>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
