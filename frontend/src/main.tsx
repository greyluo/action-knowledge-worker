import { createRoot } from 'react-dom/client'
import './styles/tokens.css'
import './App.css'
import App from './App'

// StrictMode removed: react-force-graph-3d's rAF animation loop crashes on
// StrictMode's dev-only double-mount because cleanup destroys the simulation
// before the queued frame fires.
createRoot(document.getElementById('root')!).render(<App />)
