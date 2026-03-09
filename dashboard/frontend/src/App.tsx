import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Layout from './components/Layout'
import Overview from './pages/Overview'
import Tasks from './pages/Tasks'
import AgentList from './pages/AgentList'
import AgentDetail from './pages/AgentDetail'
import Timeline from './pages/Timeline'
import Costs from './pages/Costs'
import Messages from './pages/Messages'
import Strategy from './pages/Strategy'
import Conversation from './pages/Conversation'
import Health from './pages/Health'
import Controls from './pages/Controls'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      retry: 1,
    },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Overview />} />
            <Route path="/conversation" element={<Conversation />} />
            <Route path="/tasks" element={<Tasks />} />
            <Route path="/agents" element={<AgentList />} />
            <Route path="/agents/:id" element={<AgentDetail />} />
            <Route path="/timeline" element={<Timeline />} />
            <Route path="/costs" element={<Costs />} />
            <Route path="/messages" element={<Messages />} />
            <Route path="/strategy" element={<Strategy />} />
            <Route path="/health" element={<Health />} />
            <Route path="/controls" element={<Controls />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
