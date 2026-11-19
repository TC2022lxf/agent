export interface Starter {
  id: string
  title: string
  note: string
  prompt: string
  swatch: string
}

/** Left column: the sentence is enough. */
export const PROMPT_STARTERS: Starter[] = [
  { id: 'white', title: '白底主图', note: '商品居中，无文字', prompt: '做一张纯白背景的电商主图，商品居中，不要文字和水印。', swatch: 'linear-gradient(180deg,#fff,#eceae4)' },
  { id: 'scene', title: '使用场景', note: '放进真实环境', prompt: '把商品放进真实使用场景，光线自然，不要加促销文字。', swatch: 'linear-gradient(180deg,#d7e6ef,#f3efe6)' },
  { id: 'detail', title: '细节特写', note: '材质和结构', prompt: '做一张突出材质和结构的特写，背景干净，不要加文字。', swatch: 'linear-gradient(180deg,#e7e0d4,#f7f4ee)' },
  { id: 'life', title: '生活方式', note: '人物与商品同框', prompt: '做一张有人正在使用商品的生活方式图，不要加标题和价格。', swatch: 'linear-gradient(180deg,#f3d7c8,#efe6da)' },
]

/** Right column: the user adds a reference picture in the dialog. */
export const REFERENCE_STARTERS: Starter[] = [
  { id: 'to-white', title: '换成白底', note: '保留商品，去掉背景', prompt: '保留图中的商品，换成纯白背景，不要文字和水印。', swatch: 'linear-gradient(180deg,#f7f7f7,#dedad2)' },
  { id: 'to-scene', title: '放进场景', note: '按参考图换环境', prompt: '保留图中的商品外观，把它放进一个干净的使用场景，不要加促销文字。', swatch: 'linear-gradient(180deg,#c9d7c2,#f3efe6)' },
  { id: 'to-angle', title: '换个角度', note: '同一件商品', prompt: '参考这张图里的商品，换一个更能看清结构的角度，背景保持干净。', swatch: 'linear-gradient(180deg,#d5dbe3,#f4f1ea)' },
  { id: 'to-crop', title: '突出主体', note: '裁掉杂物', prompt: '以这张图为参考，只保留商品主体并放大，去掉配件和文字。', swatch: 'linear-gradient(180deg,#e6d3c4,#f7f4ee)' },
]

export const FILE_STARTER = '写一个商品营销活动倒计时 HTML 页面，保存为 page.html，页面要有标题、倒计时和购买按钮。'

export const PDP_STARTERS: Starter[] = [
  { id: 'from-scratch', title: '从零写一套 PDP', note: '标题、五点、描述', prompt: '从零写一套亚马逊 PDP：标题、五点和描述，并配一张主图。', swatch: 'linear-gradient(180deg,#e7efe8,#f7f4ee)' },
  { id: 'optimize', title: '优化已有 Listing', note: '在导入稿上改', prompt: '在现有 Listing 上优化标题和五点，不要编造商品里没有的事实。', swatch: 'linear-gradient(180deg,#e4e7f2,#f6f4ef)' },
  { id: 'title-only', title: '只改标题', note: '其余槽位不动', prompt: '只改标题，让它更短、更能搜到，五点、描述和图片都不要动。', swatch: 'linear-gradient(180deg,#f3e6d4,#f7f4ee)' },
]

export const RATIOS = ['自动', '1:1', '4:5', '16:9'] as const
export type Ratio = (typeof RATIOS)[number]

export function withRatio(prompt: string, ratio: Ratio): string {
  if (ratio === '自动') return prompt
  return `${prompt} 画面宽高比 ${ratio}。`
}

export function pdpBrief(fields: { name: string; brand: string; points: string; site: string }, lead: string): string {
  const bits = [
    lead,
    fields.name && `商品：${fields.name}`,
    fields.brand && `品牌：${fields.brand}`,
    fields.site && `站点：${fields.site}`,
    fields.points && `卖点和人群：${fields.points}`,
  ].filter(Boolean)
  return bits.join('\n')
}
