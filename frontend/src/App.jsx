import { useState } from 'react';
import Navbar from './components/Navbar';
import KPISummary from './components/KPISummary';
import UploadPanel from './components/UploadPanel';
import ReviewTable from './components/ReviewTable';

function App() {
  const [uploadOpen, setUploadOpen] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const triggerRefresh = () => setRefreshKey((prev) => prev + 1);

  return (
    <div className="min-h-screen bg-[#0f172a]">
      <Navbar onUploadClick={() => setUploadOpen(true)} />
      
      <main className="mx-auto max-w-screen-2xl p-6">
        <KPISummary refreshKey={refreshKey} />
        <ReviewTable refreshKey={refreshKey} onRefresh={triggerRefresh} />
      </main>

      <UploadPanel 
        open={uploadOpen} 
        onClose={() => setUploadOpen(false)} 
        onSuccess={triggerRefresh} 
      />
    </div>
  );
}

export default App;
