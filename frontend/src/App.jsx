import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import EditorPage from './pages/EditorPage';
import SettingsPage from './components/SettingsPage';
import Boardroom from './components/Boardroom';
import './index.css';

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<EditorPage />} />
        {/* SettingsPage and Boardroom are technically used as Modals within EditorPage previously,
            but routing them explicitly allows for modular navigation if needed. 
            For now, EditorPage handles showing modals, so we preserve its logic. */}
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/boardroom" element={<Boardroom />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
