export type BodyBlock =
  | { type: 'p'; text: string }
  | { type: 'h2'; text: string }
  | { type: 'quote'; text: string; cite?: string }
  | { type: 'list'; items: string[] };

export type Post = {
  slug: string;
  title: string;
  excerpt: string;
  category: string;
  date: string;
  dateLabel: string;
  readTime: string;
  featured?: boolean;
  accent: 'coral' | 'blue' | 'green' | 'yellow';
  coverLabel: string;
  tags: string[];
  body: BodyBlock[];
};

type StoredPost = Omit<Post, 'dateLabel'>;

// Each article is a single reviewable change. Astro renders the data as text, not HTML.
const articleFiles = import.meta.glob<StoredPost>('./content/blog/*.json', { eager: true, import: 'default' });
export const posts: Post[] = Object.entries(articleFiles).map(([path, post]) => {
  if (path !== `./content/blog/${post.slug}.json`) throw new Error(`Article filename does not match its slug: ${path}`);
  return { ...post, dateLabel: post.date.replaceAll('-', '.') };
}).sort((a, b) => b.date.localeCompare(a.date) || a.slug.localeCompare(b.slug));
if (!posts.length) throw new Error('The blog requires at least one article');

export const projects = [
  {
    title: 'Field Notes',
    type: 'Digital garden',
    description: '一个把阅读、观察和小实验串起来的个人知识花园。',
    year: '2026',
    tags: ['Astro', 'Content'],
    accent: 'coral',
    href: '/blog/building-this-little-corner/'
  },
  {
    title: 'Tiny Habit',
    type: 'Web app',
    description: '用最少的界面，记录那些值得重复的小动作。',
    year: '2025',
    tags: ['Product', 'Prototype'],
    accent: 'blue',
    href: '/lab/'
  },
  {
    title: 'Open Desk',
    type: 'Design system',
    description: '一套给独立创作者使用的开放式界面组件和写作模板。',
    year: '2025',
    tags: ['UI', 'Open source'],
    accent: 'green',
    href: '/projects/'
  }
] as const;

export const labs = [
  { number: '01', title: 'Color weather', description: '把今日天气翻译成一组可以带走的颜色。', status: 'Playground', accent: 'coral' },
  { number: '02', title: 'One line a day', description: '一个只允许写一句话的极简日记本。', status: 'Prototype', accent: 'blue' },
  { number: '03', title: 'Slow clock', description: '给注意力一个不那么着急的节拍器。', status: 'In progress', accent: 'green' }
] as const;
