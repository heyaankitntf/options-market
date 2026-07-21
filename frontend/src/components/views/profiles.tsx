'use client'

import * as React from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Workflow, Plus, Play, Pause, Pencil, Trash2, Zap, Clock, CheckCircle2,
  AlertCircle, RefreshCw, Loader2,
} from 'lucide-react'
import { api, type Profile, type FormulaTemplate } from '@/lib/api'
import { SYMBOL_SPECS } from '@/lib/symbols'
import { fmtNum, fmtDateTime, relTime } from '@/lib/format'
import { SectionHeader, StatusBadge, EmptyState, MiniBar } from '@/components/ui/primitives'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogTrigger } from '@/components/ui/dialog'
import { Checkbox } from '@/components/ui/checkbox'
import { useToast } from '@/hooks/use-toast'
import { cn } from '@/lib/utils'

export function ProfilesView() {
  const qc = useQueryClient()
  const { toast } = useToast()
  const { data: profiles, isLoading } = useQuery({
    queryKey: ['profiles'],
    queryFn: () => api<Profile[]>('/api/profiles'),
    refetchInterval: 10000,
  })
  const { data: templates } = useQuery({ queryKey: ['templates'], queryFn: () => api<FormulaTemplate[]>('/api/templates') })
  const { data: channels } = useQuery({ queryKey: ['channels'], queryFn: () => api<{ id: string; name: string; type: string; enabled: boolean }[]>('/api/channels') })

  const [editing, setEditing] = React.useState<Profile | null>(null)
  const [creating, setCreating] = React.useState(false)
  const [busy, setBusy] = React.useState<string | null>(null)

  const run = async (id: string) => {
    setBusy(id)
    try {
      await api(`/api/profiles/${id}/run`, { method: 'POST' })
      toast({ title: 'Pipeline triggered', description: 'Check Executions for progress' })
      qc.invalidateQueries({ queryKey: ['profiles'] })
    } catch (e) {
      toast({ title: 'Failed', description: String(e), variant: 'destructive' })
    } finally { setBusy(null) }
  }

  const togglePause = async (p: Profile) => {
    try {
      await api(`/api/profiles/${p.id}/toggle`, { method: 'POST', body: JSON.stringify({ paused: !p.paused }) })
      toast({ title: p.paused ? 'Resumed' : 'Paused', description: p.name })
      qc.invalidateQueries({ queryKey: ['profiles'] })
    } catch (e) { toast({ title: 'Failed', description: String(e), variant: 'destructive' }) }
  }

  const toggleEnabled = async (p: Profile) => {
    try {
      await api(`/api/profiles/${p.id}`, { method: 'PATCH', body: JSON.stringify({ enabled: !p.enabled }) })
      qc.invalidateQueries({ queryKey: ['profiles'] })
    } catch (e) { toast({ title: 'Failed', description: String(e), variant: 'destructive' }) }
  }

  const remove = async (p: Profile) => {
    if (!confirm(`Delete profile "${p.name}"? This removes all related data.`)) return
    try {
      await api(`/api/profiles/${p.id}`, { method: 'DELETE' })
      toast({ title: 'Profile deleted' })
      qc.invalidateQueries({ queryKey: ['profiles'] })
    } catch (e) { toast({ title: 'Failed', description: String(e), variant: 'destructive' }) }
  }

  return (
    <div className="space-y-4">
      <Card className="p-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Workflow className="h-5 w-5 text-primary" />
          <div>
            <div className="font-semibold">Automation Profiles</div>
            <div className="text-xs text-muted-foreground">{profiles?.filter(p => p.enabled && !p.paused).length ?? 0} active · {profiles?.length ?? 0} total</div>
          </div>
        </div>
        <Button className="gap-1.5" onClick={() => setCreating(true)}>
          <Plus className="h-4 w-4" /> New Profile
        </Button>
      </Card>

      {isLoading ? (
        <Card className="p-8 text-center text-muted-foreground">Loading profiles…</Card>
      ) : !profiles?.length ? (
        <Card className="p-0"><EmptyState icon={<Workflow className="h-8 w-8" />} title="No profiles yet" description="Create your first automation profile." action={<Button onClick={() => setCreating(true)} className="gap-1.5"><Plus className="h-4 w-4" /> New Profile</Button>} /></Card>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
          {profiles.map((p) => (
            <ProfileCard
              key={p.id}
              p={p}
              busy={busy === p.id}
              onRun={() => run(p.id)}
              onTogglePause={() => togglePause(p)}
              onToggleEnabled={() => toggleEnabled(p)}
              onEdit={() => setEditing(p)}
              onDelete={() => remove(p)}
            />
          ))}
        </div>
      )}

      <ProfileDialog
        open={creating || !!editing}
        profile={editing}
        templates={templates ?? []}
        channels={channels ?? []}
        onClose={() => { setCreating(false); setEditing(null) }}
        onSaved={() => { setCreating(false); setEditing(null); qc.invalidateQueries({ queryKey: ['profiles'] }) }}
      />
    </div>
  )
}

function ProfileCard({
  p, busy, onRun, onTogglePause, onToggleEnabled, onEdit, onDelete,
}: {
  p: Profile; busy: boolean; onRun: () => void; onTogglePause: () => void; onToggleEnabled: () => void; onEdit: () => void; onDelete: () => void;
}) {
  const spec = SYMBOL_SPECS.find((s) => s.symbol === p.symbol)
  const successRate = p.runCount > 0 ? Math.round((p.successCount / p.runCount) * 100) : 0
  return (
    <Card className="p-4 flex flex-col gap-3">
      <div className="flex items-start gap-3">
        <div className="h-10 w-10 rounded-lg bg-primary/12 border border-primary/20 flex items-center justify-center text-primary font-semibold text-xs shrink-0">
          {p.symbol.slice(0, 4)}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-semibold truncate">{p.name}</span>
            {p.lastStatus && <StatusBadge status={p.lastStatus} />}
          </div>
          <div className="text-xs text-muted-foreground">{p.symbol} · {p.exchange} · {p.expiryKind} expiry</div>
        </div>
        <Switch checked={p.enabled} onCheckedChange={onToggleEnabled} />
      </div>

      <div className="grid grid-cols-3 gap-2 text-center">
        <div className="rounded-md bg-muted/40 py-1.5">
          <div className="text-[10px] text-muted-foreground uppercase">Interval</div>
          <div className="text-sm font-semibold tnum">{p.intervalMin}m</div>
        </div>
        <div className="rounded-md bg-muted/40 py-1.5">
          <div className="text-[10px] text-muted-foreground uppercase">Runs</div>
          <div className="text-sm font-semibold tnum">{p.runCount}</div>
        </div>
        <div className="rounded-md bg-muted/40 py-1.5">
          <div className="text-[10px] text-muted-foreground uppercase">Success</div>
          <div className="text-sm font-semibold tnum">{successRate}%</div>
        </div>
      </div>

      <div>
        <div className="flex items-center justify-between text-[11px] text-muted-foreground mb-1">
          <span>Success rate</span>
          <span className="tnum">{p.successCount}/{p.runCount}</span>
        </div>
        <MiniBar value={successRate} max={100} color={successRate > 80 ? 'bg-emerald-500' : successRate > 50 ? 'bg-amber-500' : 'bg-rose-500'} />
      </div>

      <div className="flex items-center gap-3 text-xs text-muted-foreground">
        <span className="flex items-center gap-1"><Clock className="h-3 w-3" /> {p.nextRunAt && !p.paused ? relTime(p.nextRunAt) : p.paused ? 'paused' : 'disabled'}</span>
        <span className="flex items-center gap-1"><CheckCircle2 className="h-3 w-3" /> {p.lastRunAt ? relTime(p.lastRunAt) : 'never'}</span>
      </div>

      <div className="flex items-center gap-1.5 pt-1 border-t">
        <Button size="sm" className="gap-1.5 flex-1" onClick={onRun} disabled={busy || p.paused}>
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />} Run now
        </Button>
        <Button size="sm" variant="outline" onClick={onTogglePause} disabled={!p.enabled}>
          {p.paused ? <Play className="h-3.5 w-3.5" /> : <Pause className="h-3.5 w-3.5" />}
        </Button>
        <Button size="icon" variant="outline" onClick={onEdit}><Pencil className="h-3.5 w-3.5" /></Button>
        <Button size="icon" variant="outline" className="text-rose-500 hover:text-rose-400" onClick={onDelete}><Trash2 className="h-3.5 w-3.5" /></Button>
      </div>
    </Card>
  )
}

function ProfileDialog({
  open, profile, templates, channels, onClose, onSaved,
}: {
  open: boolean
  profile: Profile | null
  templates: FormulaTemplate[]
  channels: { id: string; name: string; type: string; enabled: boolean }[]
  onClose: () => void
  onSaved: () => void
}) {
  const { toast } = useToast()
  const [form, setForm] = React.useState({
    name: '', symbol: 'NIFTY', exchange: 'NFO', expiryKind: 'weekly', expiryDate: '',
    intervalMin: 10, templateId: '', outputFormats: 'json,csv', allStrikes: true,
    enabled: true, paused: false, notifyChannels: [] as string[],
  })

  React.useEffect(() => {
    if (profile) {
      setForm({
        name: profile.name, symbol: profile.symbol, exchange: profile.exchange,
        expiryKind: profile.expiryKind, expiryDate: profile.expiryDate ?? '',
        intervalMin: profile.intervalMin, templateId: profile.templateId ?? '',
        outputFormats: profile.outputFormats, allStrikes: profile.allStrikes,
        enabled: profile.enabled, paused: profile.paused,
        notifyChannels: profile.notifyChannels.split(',').filter(Boolean),
      })
    } else {
      setForm({
        name: '', symbol: 'NIFTY', exchange: 'NFO', expiryKind: 'weekly', expiryDate: '',
        intervalMin: 10, templateId: '', outputFormats: 'json,csv', allStrikes: true,
        enabled: true, paused: false, notifyChannels: [],
      })
    }
  }, [profile, open])

  const save = async () => {
    if (!form.name.trim()) { toast({ title: 'Name required', variant: 'destructive' }); return }
    try {
      const body = { ...form, intervalMin: Number(form.intervalMin) }
      if (profile) {
        await api(`/api/profiles/${profile.id}`, { method: 'PATCH', body: JSON.stringify(body) })
        toast({ title: 'Profile updated' })
      } else {
        await api('/api/profiles', { method: 'POST', body: JSON.stringify(body) })
        toast({ title: 'Profile created' })
      }
      onSaved()
    } catch (e) {
      toast({ title: 'Save failed', description: String(e), variant: 'destructive' })
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-2xl max-h-[90vh] overflow-y-auto scroll-thin">
        <DialogHeader>
          <DialogTitle>{profile ? 'Edit Profile' : 'New Automation Profile'}</DialogTitle>
        </DialogHeader>
        <div className="grid grid-cols-2 gap-4 py-2">
          <div className="col-span-2">
            <Label>Profile Name</Label>
            <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="e.g. Nifty Weekly Auto" />
          </div>
          <div>
            <Label>Symbol</Label>
            <Select value={form.symbol} onValueChange={(v) => setForm({ ...form, symbol: v })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {SYMBOL_SPECS.map((s) => <SelectItem key={s.symbol} value={s.symbol}>{s.symbol} — {s.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label>Exchange</Label>
            <Select value={form.exchange} onValueChange={(v) => setForm({ ...form, exchange: v })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>{['NFO', 'BFO', 'MCX'].map((e) => <SelectItem key={e} value={e}>{e}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div>
            <Label>Expiry Kind</Label>
            <Select value={form.expiryKind} onValueChange={(v) => setForm({ ...form, expiryKind: v })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>{['weekly', 'monthly'].map((e) => <SelectItem key={e} value={e} className="capitalize">{e}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div>
            <Label>Expiry Date Override (optional)</Label>
            <Input type="date" value={form.expiryDate} onChange={(e) => setForm({ ...form, expiryDate: e.target.value })} />
          </div>
          <div>
            <Label>Refresh Interval (minutes)</Label>
            <Input type="number" min={1} max={60} value={form.intervalMin} onChange={(e) => setForm({ ...form, intervalMin: Number(e.target.value) })} />
          </div>
          <div>
            <Label>Calculation Template</Label>
            <Select value={form.templateId} onValueChange={(v) => setForm({ ...form, templateId: v })}>
              <SelectTrigger><SelectValue placeholder="Default" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="">Default</SelectItem>
                {templates.map((t) => <SelectItem key={t.id} value={t.id}>{t.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="col-span-2">
            <Label>Output Formats</Label>
            <div className="flex gap-3 mt-1.5">
              {['json', 'csv', 'xlsx', 'pdf'].map((f) => (
                <label key={f} className="flex items-center gap-1.5 text-sm cursor-pointer">
                  <Checkbox
                    checked={form.outputFormats.split(',').includes(f)}
                    onCheckedChange={(c) => {
                      const arr = form.outputFormats.split(',').filter(Boolean)
                      const next = c ? [...arr, f] : arr.filter((x) => x !== f)
                      setForm({ ...form, outputFormats: next.join(',') })
                    }}
                  />
                  <span className="uppercase text-xs">{f}</span>
                </label>
              ))}
            </div>
          </div>
          <div className="col-span-2">
            <Label>Notification Channels</Label>
            <div className="space-y-1.5 mt-1.5">
              {channels.length === 0 && <p className="text-xs text-muted-foreground">No channels configured — add some in Notifications.</p>}
              {channels.map((ch) => (
                <label key={ch.id} className="flex items-center gap-2 text-sm cursor-pointer">
                  <Checkbox
                    checked={form.notifyChannels.includes(ch.id)}
                    onCheckedChange={(c) => {
                      setForm({
                        ...form,
                        notifyChannels: c ? [...form.notifyChannels, ch.id] : form.notifyChannels.filter((x) => x !== ch.id),
                      })
                    }}
                  />
                  <span>{ch.name}</span>
                  <Badge variant="outline" className="text-[10px] capitalize">{ch.type}</Badge>
                  {!ch.enabled && <Badge variant="secondary" className="text-[10px]">disabled</Badge>}
                </label>
              ))}
            </div>
          </div>
          <div className="col-span-2 flex items-center gap-6 pt-2">
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <Switch checked={form.allStrikes} onCheckedChange={(c) => setForm({ ...form, allStrikes: c })} />
              All Strikes
            </label>
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <Switch checked={form.enabled} onCheckedChange={(c) => setForm({ ...form, enabled: c })} />
              Enabled
            </label>
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <Switch checked={form.paused} onCheckedChange={(c) => setForm({ ...form, paused: c })} />
              Start Paused
            </label>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={save}>{profile ? 'Save Changes' : 'Create Profile'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
