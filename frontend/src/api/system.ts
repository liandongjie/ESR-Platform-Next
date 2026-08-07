import { http } from '@/api/http'
import type { Capabilities, LiveHealth } from '@/types/system'

export async function getLiveHealth(): Promise<LiveHealth> {
  const response = await http.get<LiveHealth>('/health/live')
  return response.data
}

export async function getCapabilities(): Promise<Capabilities> {
  const response = await http.get<Capabilities>('/meta/capabilities')
  return response.data
}
