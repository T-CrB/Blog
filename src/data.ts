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

export const posts: Post[] = [
  {
    slug: 'make-space-for-better-thinking',
    title: '给好想法留一点空白',
    excerpt: '从整理桌面到整理接口：为什么「留白」不是浪费，而是一种主动的设计能力。',
    category: 'Design notes',
    date: '2026-11-18',
    dateLabel: '2026.11.18',
    readTime: '6 min read',
    featured: true,
    accent: 'coral',
    coverLabel: '01 / space',
    tags: ['设计', '工作方法'],
    body: [
      { type: 'p', text: '我越来越相信，真正改变工作质量的，往往不是再增加一个工具，而是给已经存在的东西留出被看见、被理解和被重新组合的空间。' },
      { type: 'p', text: '这篇文章写给那些总是把页面塞得很满、把日程排得很密、把想法记在十几个地方的人。也写给过去的我。' },
      { type: 'h2', text: '留白不是空着不做事' },
      { type: 'p', text: '在视觉设计里，留白让元素之间的关系变得清晰；在工作里，留白让我们有机会意识到：当前正在做的事，是否仍然值得做。它不是一块被放弃的区域，而是一种主动的注意力分配。' },
      { type: 'quote', text: 'The details are not the details. They make the design.', cite: '— Charles Eames' },
      { type: 'h2', text: '我的三个小实验' },
      { type: 'list', items: ['把每周一上午留给没有明确产出的探索。', '在交付前留出一轮「什么都不改」的完整阅读。', '给每个新想法一个最小可见的原型，而不是一份完美计划。'] },
      { type: 'p', text: '当空间被留出来，很多答案不会立刻出现，但问题会开始变得诚实。对我来说，这已经是非常高的回报。' }
    ]
  },
  {
    slug: 'a-small-system-for-side-projects',
    title: '我如何管理那些还没长大的项目',
    excerpt: '一个轻量的 side project 系统：从灵感收集，到每周一次的可见进度。',
    category: 'Build log',
    date: '2026-11-09',
    dateLabel: '2026.11.09',
    readTime: '8 min read',
    accent: 'blue',
    coverLabel: '02 / system',
    tags: ['独立开发', '效率'],
    body: [
      { type: 'p', text: '个人项目最容易发生的事，是在「想做」和「正在做」之间无限循环。为了打破循环，我给自己搭了一个足够小、但可以持续使用的系统。' },
      { type: 'h2', text: '只保留三个状态' },
      { type: 'p', text: '收集箱、正在做、已经发布。没有「以后再说」这个状态——因为它通常只是收集箱的另一个名字。' },
      { type: 'p', text: '每周我只允许一个项目进入「正在做」。其他想法仍然可以被记录，但不会占用正在建设的注意力。' },
      { type: 'h2', text: '进度必须能被看见' },
      { type: 'list', items: ['每个项目写一句“它为谁解决什么问题”。', '每周只设一个能在周日展示出来的结果。', '如果连续两周没有产出，就把它移回收集箱。'] },
      { type: 'p', text: '这套规则并不神奇，甚至有点笨。但它让我重新拥有了一种很重要的感觉：项目不是在等待我变得更有空，而是在今天就可以向前走一小步。' }
    ]
  },
  {
    slug: 'notes-from-a-quiet-interface',
    title: '安静的界面，清晰的动作',
    excerpt: '关于按钮、层级和微小反馈：一个界面如何在不打扰人的前提下，告诉你下一步是什么。',
    category: 'Interface craft',
    date: '2026-10-28',
    dateLabel: '2026.10.28',
    readTime: '5 min read',
    accent: 'green',
    coverLabel: '03 / interface',
    tags: ['界面', '产品'],
    body: [
      { type: 'p', text: '好的界面不是把所有可能都展示出来，而是在正确的时机，把正确的下一步交到用户手里。' },
      { type: 'h2', text: '安静不等于没有个性' },
      { type: 'p', text: '我喜欢克制的页面，但克制并不意味着把颜色、声音和动效全部拿走。安静的界面仍然可以有温度，只是它不会为了证明自己存在而抢走注意力。' },
      { type: 'quote', text: 'Make the important things obvious, and the rest quiet.', cite: '— A note from my sketchbook' },
      { type: 'p', text: '在实际工作中，我会先问三个问题：用户现在知道自己在哪里吗？他知道下一步能做什么吗？完成动作后，界面有没有给出足够的回应？' }
    ]
  },
  {
    slug: 'building-this-little-corner',
    title: '搭建这个小角落',
    excerpt: '为什么我选择 Astro，以及一个个人网站如何同时像花园、档案馆和工作台。',
    category: 'Behind the site',
    date: '2026-10-12',
    dateLabel: '2026.10.12',
    readTime: '4 min read',
    accent: 'yellow',
    coverLabel: '04 / home',
    tags: ['建站', 'Astro'],
    body: [
      { type: 'p', text: '个人网站是一个很奇妙的东西：它不必服务于增长曲线，却可以持续积累信任。这里是我把工作、兴趣和正在学习的东西放在一起的地方。' },
      { type: 'h2', text: '像一座慢慢长大的房子' },
      { type: 'p', text: '我希望它不像一个一次性交付的宣传页，而更像一座会随着生活变化而调整的房子：首页是门廊，文章是书架，项目是工作台，实验室则是一间可以弄乱的房间。' },
      { type: 'p', text: '所以我选择静态优先的结构，让内容尽量轻，让页面尽量快，也让每一次更新都保持一点手工感。' }
    ]
  }
];

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
