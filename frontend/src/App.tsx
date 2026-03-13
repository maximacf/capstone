import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Taxonomy from './pages/Taxonomy'
import ExecutionHistory from './pages/ExecutionHistory'
import Evaluation from './pages/Evaluation'

function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/taxonomy" element={<Taxonomy />} />
          <Route path="/execution" element={<ExecutionHistory />} />
          <Route path="/evaluation" element={<Evaluation />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  )
}

export default App
