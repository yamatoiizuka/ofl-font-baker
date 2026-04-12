/**
 * @fileoverview Application entry point — mounts React root and disables default drag-and-drop navigation.
 */

import React from 'react';
import { createRoot } from 'react-dom/client';
import App from '@/renderer/App';
import '@/renderer/index.css';

// Prevent the browser from opening files dropped anywhere on the window
document.addEventListener('dragover', (e) => e.preventDefault());
document.addEventListener('drop', (e) => e.preventDefault());

const container = document.getElementById('root')!;
const root = createRoot(container);
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
