'use client'

import * as React from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Settings, KeyRound, Calculator, Users, Cog, Plus, Trash2, Power, Shield,
  Lock, Eye, Database, RefreshCw, CheckCircle2, AlertCircle, Save,
} from 'lucide-react'
import { api, type Credential, type FormulaTemplate, type User } from '@/lib/api'
import { fmtDateTime } from '@/lib/format'
import { SectionHeader, EmptyState, StatusBadge } from '@/components/ui/primitives'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { useToast } from '@/hooks/use-toast'
import { cn } from '@/lib/utils'

export function AdminView() {
  return (
    <Tabs defaultValue="credentials">
      <TabsList className="flex-wrap h-auto">
        <TabsTrigger value="credentials" className="gap-1.5"><KeyRound className="h-3.5 w-3.5" /> Credentials</TabsTrigger>
        <TabsTrigger value="templates" className="gap-1.5"><Calculator className="h-3.5 w-3.5" /> Formula Templates</TabsTrigger>
        <TabsTrigger value="users" className="gap-1.5"><Users className="h-3.5 w-3.5" /> Users & RBAC</TabsTrigger>
        <TabsTrigger value="settings" className="gap-1.5"><Cog className="h-3.5 w-3.5" /> System Settings</TabsTrigger>
      </TabsList>

      <TabsContent value="credentials" className="mt-4"><CredentialsPanel /></TabsContent>
      <TabsContent value="templates" className="mt-4"><TemplatesPanel /></TabsContent>
      <TabsContent value="users" className="mt-4"><UsersPanel /></TabsContent>
      <TabsContent value="settings" className="mt-4"><SettingsPanel /></TabsContent>
    </Tabs>
  )
}

// ---------------------------------------------------------------------------

function CredentialsPanel() {
  const qc = useQueryClient()
  const { toast } = useToast()
  const { data: creds } = useQuery({ queryKey: ['creds'], queryFn: () => api<Credential[]>('/api/credentials') })
  const [open, setOpen] = React.useState(false)

  const remove = async (id: string) => {
    if (!confirm('Delete this credential?')) return
    try { await api(`/api/credentials/${id}`, { method: 'DELETE' }); toast({ title: 'Credential deleted' }); qc.invalidateQueries({ queryKey: ['creds'] }) }
    catch (e) { toast({ title: 'Failed', description: String(e), variant: 'destructive' }) }
  }

  const toggle = async (c: Credential) => {
    try { await api(`/api/credentials/${c.id}`, { method: 'PATCH', body: JSON.stringify({ active: !c.active }) }); qc.invalidateQueries({ queryKey: ['creds'] }) }
    catch (e) { toast({ title: 'Failed', description: String(e), variant: 'destructive' }) }
  }

  return (
    <div className="space-y-4">
      <Card className="p-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-primary/12 flex items-center justify-center"><Lock className="h-5 w-5 text-primary" /></div>
          <div>
            <div className="font-semibold">Portal Credentials</div>
            <div className="text-xs text-muted-foreground">AES-256-GCM encrypted at rest · {creds?.length ?? 0} stored</div>
          </div>
        </div>
        <Button className="gap-1.5" onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> Add Credential</Button>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {creds?.map((c) => (
          <Card key={c.id} className="p-4">
            <div className="flex items-start gap-3">
              <div className={cn('h-9 w-9 rounded-lg flex items-center justify-center', c.active ? 'bg-emerald-500/12 text-emerald-500' : 'bg-muted text-muted-foreground')}>
                <KeyRound className="h-4 w-4" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-semibold truncate">{c.label}</span>
                  <Badge variant="outline" className="text-[10px]">{c.portal}</Badge>
                  <Badge variant={c.active ? 'secondary' : 'destructive'} className="text-[10px]">{c.active ? 'active' : 'inactive'}</Badge>
                </div>
                <div className="text-xs text-muted-foreground mt-0.5 truncate">{c.username}</div>
                <div className="flex items-center gap-1 text-[11px] text-muted-foreground mt-1">
                  <Lock className="h-3 w-3" /> password encrypted {c.hasPassword ? '••••••' : '(none)'}
                </div>
              </div>
              <div className="flex flex-col gap-1">
                <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => toggle(c)}><Power className="h-3.5 w-3.5" /></Button>
                <Button size="icon" variant="ghost" className="h-7 w-7 text-rose-500" onClick={() => remove(c.id)}><Trash2 className="h-3.5 w-3.5" /></Button>
              </div>
            </div>
            <div className="text-[11px] text-muted-foreground mt-2 pt-2 border-t">
              {c.lastUsed ? `Last used ${fmtDateTime(c.lastUsed)}` : 'Never used'}
            </div>
          </Card>
        ))}
      </div>

      <CredentialDialog open={open} onClose={() => setOpen(false)} onSaved={() => { setOpen(false); qc.invalidateQueries({ queryKey: ['creds'] }) }} />
    </div>
  )
}

function CredentialDialog({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: () => void }) {
  const { toast } = useToast()
  const [label, setLabel] = React.useState('')
  const [portal, setPortal] = React.useState('icharts')
  const [username, setUsername] = React.useState('')
  const [password, setPassword] = React.useState('')
  const [active, setActive] = React.useState(true)

  const save = async () => {
    if (!label || !username || !password) { toast({ title: 'All fields required', variant: 'destructive' }); return }
    try {
      await api('/api/credentials', { method: 'POST', body: JSON.stringify({ label, portal, username, password, active }) })
      toast({ title: 'Credential stored (encrypted)' })
      setLabel(''); setUsername(''); setPassword(''); onSaved()
    } catch (e) { toast({ title: 'Failed', description: String(e), variant: 'destructive' }) }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader><DialogTitle>New Portal Credential</DialogTitle></DialogHeader>
        <div className="space-y-3 py-2">
          <div><Label>Label</Label><Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. icharts-primary" /></div>
          <div><Label>Portal</Label><Select value={portal} onValueChange={setPortal}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{['icharts', 'nse', 'bse'].map((p) => <SelectItem key={p} value={p}>{p}</SelectItem>)}</SelectContent></Select></div>
          <div><Label>Username</Label><Input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="you@example.com" /></div>
          <div><Label>Password</Label><Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" /></div>
          <label className="flex items-center gap-2 text-sm cursor-pointer"><Switch checked={active} onCheckedChange={setActive} /> Active</label>
        </div>
        <DialogFooter><Button variant="outline" onClick={onClose}>Cancel</Button><Button onClick={save}><Lock className="h-4 w-4 mr-1.5" /> Store Encrypted</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------

function TemplatesPanel() {
  const qc = useQueryClient()
  const { toast } = useToast()
  const { data: templates } = useQuery({ queryKey: ['templates'], queryFn: () => api<FormulaTemplate[]>('/api/templates') })
  const [open, setOpen] = React.useState(false)
  const [editing, setEditing] = React.useState<FormulaTemplate | null>(null)

  const remove = async (t: FormulaTemplate) => {
    if (!confirm(`Delete template "${t.name}"?`)) return
    try { await api(`/api/templates/${t.id}`, { method: 'DELETE' }); toast({ title: 'Template deleted' }); qc.invalidateQueries({ queryKey: ['templates'] }) }
    catch (e) { toast({ title: 'Failed', description: String(e), variant: 'destructive' }) }
  }

  return (
    <div className="space-y-4">
      <Card className="p-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-primary/12 flex items-center justify-center"><Calculator className="h-5 w-5 text-primary" /></div>
          <div>
            <div className="font-semibold">Calculation Templates</div>
            <div className="text-xs text-muted-foreground">Configurable formula weights & thresholds · {templates?.length ?? 0} templates</div>
          </div>
        </div>
        <Button className="gap-1.5" onClick={() => { setEditing(null); setOpen(true) }}><Plus className="h-4 w-4" /> New Template</Button>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {templates?.map((t) => (
          <Card key={t.id} className="p-4">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-semibold truncate">{t.name}</span>
                  <Badge variant="outline" className="text-[10px]">v{t.version}</Badge>
                  <Badge variant={t.enabled ? 'secondary' : 'destructive'} className="text-[10px]">{t.enabled ? 'enabled' : 'disabled'}</Badge>
                </div>
                {t.description && <p className="text-xs text-muted-foreground mt-1">{t.description}</p>}
              </div>
              <div className="flex gap-1">
                <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => { setEditing(t); setOpen(true) }}><Settings className="h-3.5 w-3.5" /></Button>
                <Button size="icon" variant="ghost" className="h-7 w-7 text-rose-500" onClick={() => remove(t)}><Trash2 className="h-3.5 w-3.5" /></Button>
              </div>
            </div>
            <div className="mt-3 pt-3 border-t grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
              {Object.entries(t.config).map(([k, v]) => (
                <div key={k} className="flex justify-between">
                  <span className="text-muted-foreground">{k}</span>
                  <span className="font-mono tnum">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</span>
                </div>
              ))}
            </div>
          </Card>
        ))}
      </div>

      <TemplateDialog open={open} template={editing} onClose={() => { setOpen(false); setEditing(null) }} onSaved={() => { setOpen(false); setEditing(null); qc.invalidateQueries({ queryKey: ['templates'] }) }} />
    </div>
  )
}

function TemplateDialog({ open, template, onClose, onSaved }: { open: boolean; template: FormulaTemplate | null; onClose: () => void; onSaved: () => void }) {
  const { toast } = useToast()
  const [name, setName] = React.useState('')
  const [description, setDescription] = React.useState('')
  const [configText, setConfigText] = React.useState('{}')

  React.useEffect(() => {
    if (template) {
      setName(template.name); setDescription(template.description ?? ''); setConfigText(JSON.stringify(template.config, null, 2))
    } else {
      setName(''); setDescription(''); setConfigText(JSON.stringify({
        atmRange: 2, pcrBullThreshold: 1.1, pcrBearThreshold: 0.9,
        trendWeights: { pcr: 40, oiShift: 25, ivSkew: 15, chgOi: 20 }, supportResistanceLookback: 5,
      }, null, 2))
    }
  }, [template, open])

  const save = async () => {
    try { JSON.parse(configText) } catch { toast({ title: 'Config must be valid JSON', variant: 'destructive' }); return }
    try {
      if (template) {
        await api(`/api/templates/${template.id}`, { method: 'PATCH', body: JSON.stringify({ name, description, config: configText }) })
        toast({ title: 'Template updated' })
      } else {
        await api('/api/templates', { method: 'POST', body: JSON.stringify({ name, description, config: configText }) })
        toast({ title: 'Template created' })
      }
      onSaved()
    } catch (e) { toast({ title: 'Failed', description: String(e), variant: 'destructive' }) }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader><DialogTitle>{template ? 'Edit Template' : 'New Formula Template'}</DialogTitle></DialogHeader>
        <div className="space-y-3 py-2">
          <div><Label>Name</Label><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Aggressive PCR Template" /></div>
          <div><Label>Description</Label><Input value={description} onChange={(e) => setDescription(e.target.value)} /></div>
          <div><Label>Config (JSON)</Label><Textarea value={configText} onChange={(e) => setConfigText(e.target.value)} className="font-mono text-xs" rows={10} /></div>
        </div>
        <DialogFooter><Button variant="outline" onClick={onClose}>Cancel</Button><Button onClick={save}><Save className="h-4 w-4 mr-1.5" /> Save</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------

function UsersPanel() {
  const qc = useQueryClient()
  const { toast } = useToast()
  const { data: users } = useQuery({ queryKey: ['users'], queryFn: () => api<User[]>('/api/users') })
  const [open, setOpen] = React.useState(false)

  const remove = async (u: User) => {
    if (!confirm(`Delete user "${u.email}"?`)) return
    try { await api(`/api/users/${u.id}`, { method: 'DELETE' }); toast({ title: 'User deleted' }); qc.invalidateQueries({ queryKey: ['users'] }) }
    catch (e) { toast({ title: 'Failed', description: String(e), variant: 'destructive' }) }
  }

  const roleBadge = (role: string) => {
    const map: Record<string, string> = { admin: 'bg-rose-500/15 text-rose-400', operator: 'bg-sky-500/15 text-sky-400', viewer: 'bg-muted text-muted-foreground' }
    return <Badge className={cn('text-[10px]', map[role] ?? map.viewer)}>{role}</Badge>
  }

  return (
    <div className="space-y-4">
      <Card className="p-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-primary/12 flex items-center justify-center"><Shield className="h-5 w-5 text-primary" /></div>
          <div>
            <div className="font-semibold">Users & Role-Based Access</div>
            <div className="text-xs text-muted-foreground">{users?.length ?? 0} users · admin / operator / viewer</div>
          </div>
        </div>
        <Button className="gap-1.5" onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> Add User</Button>
      </Card>

      <Card className="p-0 overflow-hidden">
        <table className="w-full text-sm">
          <thead><tr className="border-b bg-muted/30 text-xs text-muted-foreground">
            <th className="px-4 py-2.5 text-left font-medium">User</th>
            <th className="px-4 py-2.5 text-left font-medium">Role</th>
            <th className="px-4 py-2.5 text-left font-medium">Status</th>
            <th className="px-4 py-2.5 text-left font-medium">Last Login</th>
            <th className="px-4 py-2.5 text-right font-medium">Actions</th>
          </tr></thead>
          <tbody>
            {users?.map((u) => (
              <tr key={u.id} className="border-b last:border-0 hover:bg-muted/30">
                <td className="px-4 py-2.5">
                  <div className="font-medium">{u.name}</div>
                  <div className="text-xs text-muted-foreground">{u.email}</div>
                </td>
                <td className="px-4 py-2.5">{roleBadge(u.role)}</td>
                <td className="px-4 py-2.5"><Badge variant={u.active ? 'secondary' : 'destructive'} className="text-[10px]">{u.active ? 'active' : 'disabled'}</Badge></td>
                <td className="px-4 py-2.5 text-xs text-muted-foreground">{u.lastLogin ? fmtDateTime(u.lastLogin) : 'never'}</td>
                <td className="px-4 py-2.5 text-right"><Button size="icon" variant="ghost" className="h-7 w-7 text-rose-500" onClick={() => remove(u)}><Trash2 className="h-3.5 w-3.5" /></Button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <UserDialog open={open} onClose={() => setOpen(false)} onSaved={() => { setOpen(false); qc.invalidateQueries({ queryKey: ['users'] }) }} />
    </div>
  )
}

function UserDialog({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: () => void }) {
  const { toast } = useToast()
  const [email, setEmail] = React.useState('')
  const [name, setName] = React.useState('')
  const [password, setPassword] = React.useState('')
  const [role, setRole] = React.useState('viewer')

  const save = async () => {
    if (!email || !password) { toast({ title: 'Email + password required', variant: 'destructive' }); return }
    try { await api('/api/users', { method: 'POST', body: JSON.stringify({ email, name: name || email.split('@')[0], password, role }) }); toast({ title: 'User created' }); setEmail(''); setName(''); setPassword(''); onSaved() }
    catch (e) { toast({ title: 'Failed', description: String(e), variant: 'destructive' }) }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader><DialogTitle>New User</DialogTitle></DialogHeader>
        <div className="space-y-3 py-2">
          <div><Label>Name</Label><Input value={name} onChange={(e) => setName(e.target.value)} /></div>
          <div><Label>Email</Label><Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></div>
          <div><Label>Password</Label><Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></div>
          <div><Label>Role</Label><Select value={role} onValueChange={setRole}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{['admin', 'operator', 'viewer'].map((r) => <SelectItem key={r} value={r} className="capitalize">{r}</SelectItem>)}</SelectContent></Select></div>
        </div>
        <DialogFooter><Button variant="outline" onClick={onClose}>Cancel</Button><Button onClick={save}>Create User</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------

function SettingsPanel() {
  const qc = useQueryClient()
  const { toast } = useToast()
  const { data, isLoading } = useQuery({ queryKey: ['settings'], queryFn: () => api<Record<string, string>>('/api/settings') })
  const [form, setForm] = React.useState<Record<string, string>>({})

  React.useEffect(() => { if (data) setForm(data) }, [data])

  const save = async () => {
    try { await api('/api/settings', { method: 'PATCH', body: JSON.stringify(form) }); toast({ title: 'Settings saved' }); qc.invalidateQueries({ queryKey: ['settings'] }) }
    catch (e) { toast({ title: 'Failed', description: String(e), variant: 'destructive' }) }
  }

  const groups: { title: string; icon: React.ReactNode; keys: [string, string][] }[] = [
    { title: 'Scheduler', icon: <RefreshCw className="h-4 w-4" />, keys: [['scheduler.enabled', 'Enable scheduler'], ['scheduler.intervalMs', 'Tick interval (ms)']] },
    { title: 'Market Hours', icon: <Database className="h-4 w-4" />, keys: [['market.hours.start', 'Open (IST)'], ['market.hours.end', 'Close (IST)']] },
    { title: 'Portal', icon: <Lock className="h-4 w-4" />, keys: [['portal.url', 'icharts URL'], ['portal.timeout', 'Timeout (ms)']] },
    { title: 'Retry Policy', icon: <RefreshCw className="h-4 w-4" />, keys: [['retry.maxAttempts', 'Max attempts'], ['retry.backoffMs', 'Backoff (ms)']] },
    { title: 'Storage', icon: <Database className="h-4 w-4" />, keys: [['storage.retentionDays', 'Retention (days)']] },
  ]

  return (
    <div className="space-y-4">
      <Card className="p-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-primary/12 flex items-center justify-center"><Cog className="h-5 w-5 text-primary" /></div>
          <div>
            <div className="font-semibold">System Configuration</div>
            <div className="text-xs text-muted-foreground">Runtime settings stored in database</div>
          </div>
        </div>
        <div className="flex gap-2">
          <Button onClick={save} className="gap-1.5"><Save className="h-4 w-4" /> Save</Button>
        </div>
      </Card>

      {isLoading ? <Card className="p-8 text-center text-muted-foreground">Loading settings…</Card> : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {groups.map((g) => (
            <Card key={g.title} className="p-4">
              <div className="flex items-center gap-2 mb-3 pb-2 border-b">
                <span className="text-primary">{g.icon}</span>
                <span className="font-semibold text-sm">{g.title}</span>
              </div>
              <div className="space-y-3">
                {g.keys.map(([k, label]) => (
                  <div key={k}>
                    <Label className="text-xs">{label}</Label>
                    <div className="text-[10px] text-muted-foreground font-mono mb-1">{k}</div>
                    <Input value={form[k] ?? ''} onChange={(e) => setForm({ ...form, [k]: e.target.value })} className="h-8 text-sm" />
                  </div>
                ))}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
