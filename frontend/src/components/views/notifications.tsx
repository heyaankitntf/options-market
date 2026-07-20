'use client'

import * as React from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Bell, Plus, Send, Mail, MessageCircle, Webhook, Trash2, Power, CheckCircle2, XCircle, Pencil,
} from 'lucide-react'
import { api, type NotificationChannel, type NotificationLog } from '@/lib/api'
import { fmtDateTime, relTime } from '@/lib/format'
import { SectionHeader, StatusBadge, EmptyState } from '@/components/ui/primitives'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { useToast } from '@/hooks/use-toast'
import { cn } from '@/lib/utils'

const channelIcon: Record<string, React.ReactNode> = {
  telegram: <Send className="h-4 w-4" />,
  email: <Mail className="h-4 w-4" />,
  whatsapp: <MessageCircle className="h-4 w-4" />,
  webhook: <Webhook className="h-4 w-4" />,
}

export function NotificationsView() {
  const qc = useQueryClient()
  const { toast } = useToast()
  const { data: channels } = useQuery({ queryKey: ['channels'], queryFn: () => api<NotificationChannel[]>('/api/channels') })
  const { data: logs } = useQuery({ queryKey: ['notif-logs'], queryFn: () => api<NotificationLog[]>('/api/notifications?limit=100'), refetchInterval: 10000 })

  const [open, setOpen] = React.useState(false)
  const [editing, setEditing] = React.useState<NotificationChannel | null>(null)

  const toggle = async (ch: NotificationChannel) => {
    try {
      await api(`/api/channels/${ch.id}`, { method: 'PATCH', body: JSON.stringify({ enabled: !ch.enabled }) })
      qc.invalidateQueries({ queryKey: ['channels'] })
    } catch (e) { toast({ title: 'Failed', description: String(e), variant: 'destructive' }) }
  }

  const remove = async (ch: NotificationChannel) => {
    if (!confirm(`Delete channel "${ch.name}"?`)) return
    try {
      await api(`/api/channels/${ch.id}`, { method: 'DELETE' })
      toast({ title: 'Channel deleted' })
      qc.invalidateQueries({ queryKey: ['channels'] })
    } catch (e) { toast({ title: 'Failed', description: String(e), variant: 'destructive' }) }
  }

  const [testing, setTesting] = React.useState<string | null>(null)
  const sendTest = async (ch: NotificationChannel) => {
    setTesting(ch.id)
    try {
      const res = await api<{ ok: boolean; message: string }>(`/api/channels/${ch.id}/test`, { method: 'POST' })
      toast({ title: res.ok ? 'Test sent' : 'Test failed', description: res.message, variant: res.ok ? 'default' : 'destructive' })
      qc.invalidateQueries({ queryKey: ['notif-logs'] })
    } catch (e) {
      toast({ title: 'Test failed', description: String(e), variant: 'destructive' })
    } finally {
      setTesting(null)
    }
  }

  const sent = logs?.filter((l) => l.status === 'sent').length ?? 0
  const failed = logs?.filter((l) => l.status === 'failed').length ?? 0

  return (
    <div className="space-y-4">
      <Tabs defaultValue="channels">
        <div className="flex items-center justify-between">
          <TabsList>
            <TabsTrigger value="channels">Channels</TabsTrigger>
            <TabsTrigger value="history">Delivery History</TabsTrigger>
          </TabsList>
          <Button className="gap-1.5" onClick={() => { setEditing(null); setOpen(true) }}>
            <Plus className="h-4 w-4" /> Add Channel
          </Button>
        </div>

        <TabsContent value="channels" className="space-y-4 mt-4">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Card className="p-4">
              <div className="text-xs text-muted-foreground">Total Channels</div>
              <div className="text-2xl font-semibold tnum">{channels?.length ?? 0}</div>
            </Card>
            <Card className="p-4">
              <div className="text-xs text-muted-foreground">Active</div>
              <div className="text-2xl font-semibold tnum text-emerald-500">{channels?.filter((c) => c.enabled).length ?? 0}</div>
            </Card>
            <Card className="p-4">
              <div className="text-xs text-muted-foreground">Sent (recent)</div>
              <div className="text-2xl font-semibold tnum">{sent}</div>
            </Card>
            <Card className="p-4">
              <div className="text-xs text-muted-foreground">Failed (recent)</div>
              <div className="text-2xl font-semibold tnum text-rose-500">{failed}</div>
            </Card>
          </div>

          {!channels?.length ? (
            <Card className="p-0"><EmptyState icon={<Bell className="h-8 w-8" />} title="No notification channels" description="Add a Telegram, email, WhatsApp or webhook channel." action={<Button onClick={() => setOpen(true)} className="gap-1.5"><Plus className="h-4 w-4" /> Add Channel</Button>} /></Card>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {channels.map((ch) => {
                let cfg: Record<string, string> = {}
                try { cfg = JSON.parse(ch.config) } catch { /* empty */ }
                return (
                  <Card key={ch.id} className="p-4">
                    <div className="flex items-start gap-3">
                      <div className={cn('h-10 w-10 rounded-lg flex items-center justify-center', ch.enabled ? 'bg-primary/15 text-primary' : 'bg-muted text-muted-foreground')}>
                        {channelIcon[ch.type] ?? <Bell className="h-4 w-4" />}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold truncate">{ch.name}</span>
                          <Badge variant="outline" className="text-[10px] capitalize">{ch.type}</Badge>
                          {!ch.enabled && <Badge variant="secondary" className="text-[10px]">disabled</Badge>}
                        </div>
                        <div className="text-xs text-muted-foreground mt-0.5 space-y-0.5">
                          {Object.entries(cfg).slice(0, 2).map(([k, v]) => (
                            <div key={k} className="truncate"><span className="opacity-60">{k}:</span> {maskVal(k, v)}</div>
                          ))}
                        </div>
                      </div>
                      <Switch checked={ch.enabled} onCheckedChange={() => toggle(ch)} />
                    </div>
                    <div className="flex items-center gap-1.5 pt-3 mt-3 border-t">
                      <Button size="sm" variant="outline" className="gap-1.5" onClick={() => { setEditing(ch); setOpen(true) }}>
                        <Pencil className="h-3.5 w-3.5" /> Edit
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className="gap-1.5"
                        disabled={testing === ch.id || !ch.enabled}
                        onClick={() => sendTest(ch)}
                      >
                        <Send className="h-3.5 w-3.5" /> {testing === ch.id ? 'Sending…' : 'Test'}
                      </Button>
                      <Button size="icon" variant="outline" className="text-rose-500 hover:text-rose-400 ml-auto" onClick={() => remove(ch)}>
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </Card>
                )
              })}
            </div>
          )}
        </TabsContent>

        <TabsContent value="history" className="mt-4">
          <Card className="p-0 overflow-hidden">
            <div className="px-4 py-3 border-b flex items-center gap-2 text-sm font-medium">
              <Bell className="h-4 w-4 text-primary" /> Delivery Log
              <Badge variant="secondary">{logs?.length ?? 0}</Badge>
            </div>
            <div className="max-h-[600px] overflow-y-auto scroll-thin">
              {!logs?.length ? (
                <EmptyState icon={<Bell className="h-8 w-8" />} title="No notifications yet" description="Reports are dispatched as profiles generate them." />
              ) : (
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-muted/50">
                    <tr className="text-xs text-muted-foreground border-b">
                      <th className="px-4 py-2.5 text-left font-medium">Status</th>
                      <th className="px-4 py-2.5 text-left font-medium">Channel</th>
                      <th className="px-4 py-2.5 text-left font-medium">Message</th>
                      <th className="px-4 py-2.5 text-right font-medium">Sent</th>
                    </tr>
                  </thead>
                  <tbody>
                    {logs.map((l) => (
                      <tr key={l.id} className="border-b last:border-0 hover:bg-muted/30">
                        <td className="px-4 py-2.5">
                          {l.status === 'sent' ? <CheckCircle2 className="h-4 w-4 text-emerald-500" /> : <XCircle className="h-4 w-4 text-rose-500" />}
                        </td>
                        <td className="px-4 py-2.5">
                          <div className="font-medium">{l.channel?.name ?? '—'}</div>
                          <div className="text-[11px] text-muted-foreground capitalize">{l.channel?.type}</div>
                        </td>
                        <td className="px-4 py-2.5 max-w-[400px]">
                          {l.error ? <span className="text-rose-400 text-xs">{l.error}</span> : <span className="text-xs truncate block">{l.message}</span>}
                        </td>
                        <td className="px-4 py-2.5 text-right text-xs text-muted-foreground">{relTime(l.createdAt)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </Card>
        </TabsContent>
      </Tabs>

      <ChannelDialog open={open} channel={editing} onClose={() => { setOpen(false); setEditing(null) }} onSaved={() => { setOpen(false); setEditing(null); qc.invalidateQueries({ queryKey: ['channels'] }) }} />
    </div>
  )
}

function maskVal(k: string, v: string): string {
  if (/token|password|secret|key/i.test(k)) return v.slice(0, 4) + '••••••' + (v.length > 10 ? v.slice(-3) : '')
  return v
}

function ChannelDialog({ open, channel, onClose, onSaved }: { open: boolean; channel: NotificationChannel | null; onClose: () => void; onSaved: () => void }) {
  const { toast } = useToast()
  const [name, setName] = React.useState('')
  const [type, setType] = React.useState('telegram')
  const [enabled, setEnabled] = React.useState(true)
  const [configText, setConfigText] = React.useState('{}')

  React.useEffect(() => {
    if (channel) {
      setName(channel.name); setType(channel.type); setEnabled(channel.enabled); setConfigText(channel.config)
    } else {
      setName(''); setType('telegram'); setEnabled(true); setConfigText('{\n  "token": "",\n  "chatId": ""\n}')
    }
  }, [channel, open])

  const save = async () => {
    try {
      JSON.parse(configText)
    } catch {
      toast({ title: 'Config must be valid JSON', variant: 'destructive' }); return
    }
    try {
      if (channel) {
        await api(`/api/channels/${channel.id}`, { method: 'PATCH', body: JSON.stringify({ name, enabled, config: configText }) })
        toast({ title: 'Channel updated' })
      } else {
        await api('/api/channels', { method: 'POST', body: JSON.stringify({ name, type, enabled, config: configText }) })
        toast({ title: 'Channel created' })
      }
      onSaved()
    } catch (e) { toast({ title: 'Failed', description: String(e), variant: 'destructive' }) }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader><DialogTitle>{channel ? 'Edit Channel' : 'New Notification Channel'}</DialogTitle></DialogHeader>
        <div className="space-y-4 py-2">
          <div>
            <Label>Channel Name</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Trading Desk Telegram" />
          </div>
          <div>
            <Label>Type</Label>
            <Select value={type} onValueChange={setType} disabled={!!channel}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {['telegram', 'email', 'whatsapp', 'webhook'].map((t) => <SelectItem key={t} value={t} className="capitalize">{t}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label>Configuration (JSON)</Label>
            <Textarea value={configText} onChange={(e) => setConfigText(e.target.value)} className="font-mono text-xs" rows={6} />
            <p className="text-[11px] text-muted-foreground mt-1">
              {type === 'telegram' && 'Keys: token, chatId'}
              {type === 'email' && 'Keys: smtp, to, from'}
              {type === 'whatsapp' && 'Keys: phone, apiKey'}
              {type === 'webhook' && 'Keys: url, headers'}
            </p>
          </div>
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <Switch checked={enabled} onCheckedChange={setEnabled} /> Enabled
          </label>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={save}>{channel ? 'Save' : 'Create'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
