import type { ReactNode } from 'react'

/** Artifact cards inside messages and grids (prototype .artifact-card). */
export function PdpCard({ label, title, desc, tags, focused, onOpen }: {
  label: string; title: string; desc: string; tags?: ReactNode; focused?: boolean; onOpen: () => void
}) {
  return (
    <button type="button" className={`artifact-card${focused ? ' is-focused' : ''}`} data-artifact="pdp" onClick={onOpen}>
      <div className="ac-thumb doc">PDP<br />{label}</div>
      <div className="ac-body">
        <div className="ac-top"><span className="ac-type">PDP</span><span className="badge badge-version">{label}</span>{tags}</div>
        <h3 className="ac-title">{title}</h3>
        <p className="ac-desc">{desc}</p>
      </div>
    </button>
  )
}

export function FileCard({ name, version, title, desc, focused, onOpen }: {
  name: string; version: string; title: string; desc: string; focused?: boolean; onOpen: () => void
}) {
  return (
    <button type="button" className={`artifact-card${focused ? ' is-focused' : ''}`} data-artifact="file" onClick={onOpen}>
      <div className="ac-thumb doc">{name}</div>
      <div className="ac-body">
        <div className="ac-top"><span className="ac-type">文件</span><span className="badge badge-version">{version}</span></div>
        <h3 className="ac-title">{title}</h3>
        <p className="ac-desc">{desc}</p>
      </div>
    </button>
  )
}

export function ImageCard({ thumb, typeLabel, version, title, desc, tags, focused, onOpen }: {
  thumb: string | undefined; typeLabel: string; version: string; title: string; desc: string
  tags?: ReactNode; focused?: boolean; onOpen: () => void
}) {
  return (
    <button type="button" className={`artifact-card${focused ? ' is-focused' : ''}`} data-artifact="image" onClick={onOpen}>
      <div className="ac-thumb img" style={thumb ? { background: `#fff url(${thumb}) center/contain no-repeat` } : undefined} />
      <div className="ac-body">
        <div className="ac-top"><span className="ac-type">{typeLabel}</span><span className="badge badge-version">{version}</span>{tags}</div>
        <h3 className="ac-title">{title}</h3>
        <p className="ac-desc">{desc}</p>
      </div>
    </button>
  )
}
