(() => {
  const canvas = document.getElementById('game');
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;

  const scoreEl = document.getElementById('score');
  const levelEl = document.getElementById('level');
  const livesEl = document.getElementById('lives');
  const overlay = document.getElementById('overlay');
  const overlayTitle = document.getElementById('overlayTitle');
  const overlaySub = document.getElementById('overlaySub');
  const startBtn = document.getElementById('startBtn');

  // ---------- audio (tiny WebAudio beeps, no assets) ----------
  let actx = null;
  function beep(freq, dur, type = 'square', vol = 0.05) {
    if (!actx) return;
    const osc = actx.createOscillator();
    const gain = actx.createGain();
    osc.type = type;
    osc.frequency.value = freq;
    gain.gain.value = vol;
    osc.connect(gain).connect(actx.destination);
    gain.gain.exponentialRampToValueAtTime(0.0001, actx.currentTime + dur);
    osc.start();
    osc.stop(actx.currentTime + dur);
  }
  function ensureAudio() {
    if (!actx) actx = new (window.AudioContext || window.webkitAudioContext)();
  }

  // ---------- constants ----------
  const PADDLE_W = 110, PADDLE_H = 14, PADDLE_SPEED = 9;
  const BALL_R = 8;
  const BRICK_ROWS_BASE = 4, BRICK_COLS = 10;
  const BRICK_W = 70, BRICK_H = 22, BRICK_GAP = 6, BRICK_TOP = 60, BRICK_LEFT = (W - (BRICK_COLS * (BRICK_W + BRICK_GAP) - BRICK_GAP)) / 2;
  const ROW_COLORS = ['#ff6b81', '#ffb14e', '#f6ff5e', '#7bf1a8', '#4fd1ff', '#b18cff'];

  // ---------- state ----------
  let score = 0, level = 1, lives = 3;
  let paddle, balls, bricks, powerups, particles, shake;
  let running = false, launched = false;
  let paddleWideTimer = 0;
  let keys = { left: false, right: false };
  let mouseX = null;

  function resetPaddle() {
    paddle = { x: W / 2 - PADDLE_W / 2, y: H - 34, w: PADDLE_W, h: PADDLE_H };
  }

  function makeBall(attached = true) {
    return {
      x: paddle.x + paddle.w / 2,
      y: paddle.y - BALL_R - 1,
      vx: 0,
      vy: 0,
      r: BALL_R,
      attached
    };
  }

  function buildBricks() {
    const rows = Math.min(BRICK_ROWS_BASE + Math.floor((level - 1) / 1), 8);
    bricks = [];
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < BRICK_COLS; c++) {
        const hp = (level >= 3 && (r + c) % 5 === 0) ? 2 : 1;
        bricks.push({
          x: BRICK_LEFT + c * (BRICK_W + BRICK_GAP),
          y: BRICK_TOP + r * (BRICK_H + BRICK_GAP),
          w: BRICK_W, h: BRICK_H,
          hp, maxHp: hp,
          color: ROW_COLORS[r % ROW_COLORS.length],
          alive: true
        });
      }
    }
  }

  function startLevel(resetScoreLives) {
    resetPaddle();
    balls = [makeBall(true)];
    powerups = [];
    particles = [];
    shake = 0;
    paddleWideTimer = 0;
    launched = false;
    buildBricks();
    updateHud();
  }

  function newGame() {
    score = 0; level = 1; lives = 3;
    startLevel();
    running = true;
  }

  function updateHud() {
    scoreEl.textContent = score;
    levelEl.textContent = level;
    livesEl.textContent = lives;
  }

  // ---------- input ----------
  canvas.addEventListener('mousemove', (e) => {
    const rect = canvas.getBoundingClientRect();
    mouseX = (e.clientX - rect.left) * (W / rect.width);
  });
  canvas.addEventListener('mousedown', () => { ensureAudio(); launchBalls(); });
  window.addEventListener('keydown', (e) => {
    if (e.code === 'ArrowLeft') keys.left = true;
    if (e.code === 'ArrowRight') keys.right = true;
    if (e.code === 'Space') { ensureAudio(); launchBalls(); e.preventDefault(); }
  });
  window.addEventListener('keyup', (e) => {
    if (e.code === 'ArrowLeft') keys.left = false;
    if (e.code === 'ArrowRight') keys.right = false;
  });

  function launchBalls() {
    if (!running) return;
    let didLaunch = false;
    for (const b of balls) {
      if (b.attached) {
        const angle = -Math.PI / 2 + (Math.random() * 0.5 - 0.25);
        const speed = 6.2 + (level - 1) * 0.35;
        b.vx = Math.cos(angle) * speed;
        b.vy = Math.sin(angle) * speed;
        b.attached = false;
        didLaunch = true;
      }
    }
    if (didLaunch) { launched = true; beep(440, 0.06, 'triangle'); }
  }

  startBtn.addEventListener('click', () => {
    ensureAudio();
    newGame();
    overlay.classList.add('hidden');
    requestAnimationFrame(loop);
  });

  // ---------- particles ----------
  function spawnParticles(x, y, color, n = 10) {
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2;
      const sp = 1.5 + Math.random() * 2.5;
      particles.push({
        x, y, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp,
        life: 1, color
      });
    }
  }

  function spawnPowerupMaybe(x, y) {
    if (Math.random() < 0.16) {
      const type = Math.random() < 0.5 ? 'wide' : 'multi';
      powerups.push({ x, y, vy: 2.4, type });
    }
  }

  // ---------- physics / update ----------
  function updatePaddle() {
    if (mouseX !== null) {
      paddle.x = mouseX - paddle.w / 2;
    }
    if (keys.left) paddle.x -= PADDLE_SPEED;
    if (keys.right) paddle.x += PADDLE_SPEED;
    paddle.x = Math.max(0, Math.min(W - paddle.w, paddle.x));

    if (paddleWideTimer > 0) {
      paddleWideTimer--;
      if (paddleWideTimer === 0) paddle.w = PADDLE_W;
    }
  }

  function updateBalls() {
    for (const b of balls) {
      if (b.attached) {
        b.x = paddle.x + paddle.w / 2;
        b.y = paddle.y - b.r - 1;
        continue;
      }
      b.x += b.vx;
      b.y += b.vy;

      if (b.x - b.r < 0) { b.x = b.r; b.vx *= -1; beep(220, 0.04); }
      if (b.x + b.r > W) { b.x = W - b.r; b.vx *= -1; beep(220, 0.04); }
      if (b.y - b.r < 0) { b.y = b.r; b.vy *= -1; beep(220, 0.04); }

      // paddle collision
      if (b.vy > 0 && b.y + b.r >= paddle.y && b.y + b.r <= paddle.y + paddle.h + 8 &&
          b.x >= paddle.x - b.r && b.x <= paddle.x + paddle.w + b.r) {
        const hitPos = (b.x - (paddle.x + paddle.w / 2)) / (paddle.w / 2); // -1..1
        const speed = Math.min(Math.hypot(b.vx, b.vy) * 1.03, 13);
        const angle = hitPos * (Math.PI / 3); // up to 60deg
        b.vx = Math.sin(angle) * speed;
        b.vy = -Math.abs(Math.cos(angle) * speed);
        b.y = paddle.y - b.r - 0.5;
        beep(330, 0.05, 'triangle');
        shake = Math.max(shake, 3);
      }

      // brick collisions
      for (const brick of bricks) {
        if (!brick.alive) continue;
        if (b.x + b.r > brick.x && b.x - b.r < brick.x + brick.w &&
            b.y + b.r > brick.y && b.y - b.r < brick.y + brick.h) {
          const overlapX = Math.min(b.x + b.r - brick.x, brick.x + brick.w - (b.x - b.r));
          const overlapY = Math.min(b.y + b.r - brick.y, brick.y + brick.h - (b.y - b.r));
          if (overlapX < overlapY) b.vx *= -1; else b.vy *= -1;

          brick.hp -= 1;
          shake = Math.max(shake, 5);
          if (brick.hp <= 0) {
            brick.alive = false;
            score += 10 * level;
            spawnParticles(brick.x + brick.w / 2, brick.y + brick.h / 2, brick.color, 12);
            spawnPowerupMaybe(brick.x + brick.w / 2, brick.y + brick.h / 2);
            beep(520 + Math.random() * 200, 0.06, 'square');
          } else {
            score += 4 * level;
            beep(300, 0.04, 'square');
          }
          updateHud();
          break;
        }
      }
    }

    // remove balls that fell off
    balls = balls.filter(b => b.attached || b.y - b.r < H + 40);

    if (balls.length === 0) {
      lives -= 1;
      updateHud();
      if (lives <= 0) {
        endGame(false);
      } else {
        balls = [makeBall(true)];
        launched = false;
      }
    }

    if (bricks.every(br => !br.alive)) {
      level += 1;
      startLevel();
    }
  }

  function updatePowerups() {
    for (const p of powerups) {
      p.y += p.vy;
      if (p.y + 10 >= paddle.y && p.y - 10 <= paddle.y + paddle.h &&
          p.x >= paddle.x && p.x <= paddle.x + paddle.w) {
        p.collected = true;
        applyPowerup(p.type);
        beep(700, 0.08, 'sine', 0.06);
      }
    }
    powerups = powerups.filter(p => !p.collected && p.y < H + 20);
  }

  function applyPowerup(type) {
    if (type === 'wide') {
      paddle.w = PADDLE_W * 1.6;
      paddleWideTimer = 60 * 9;
    } else if (type === 'multi') {
      const base = balls.find(b => !b.attached) || balls[0];
      if (base) {
        for (let i = 0; i < 2; i++) {
          const angle = (Math.random() * 1.2 - 0.6) - Math.PI / 2;
          const speed = Math.hypot(base.vx, base.vy) || 6.5;
          balls.push({
            x: base.x, y: base.y,
            vx: Math.cos(angle) * speed, vy: Math.sin(angle) * speed,
            r: BALL_R, attached: false
          });
        }
      }
    }
  }

  function updateParticles() {
    for (const p of particles) {
      p.x += p.vx; p.y += p.vy; p.vy += 0.08; p.life -= 0.03;
    }
    particles = particles.filter(p => p.life > 0);
    if (shake > 0) shake *= 0.85;
    if (shake < 0.05) shake = 0;
  }

  function endGame(won) {
    running = false;
    overlay.classList.remove('hidden');
    overlayTitle.textContent = won ? 'You Win!' : 'Game Over';
    overlaySub.textContent = `Score: ${score} · Level ${level}`;
    startBtn.textContent = 'Play Again';
  }

  // ---------- render ----------
  function draw() {
    ctx.save();
    if (shake > 0) {
      ctx.translate((Math.random() - 0.5) * shake, (Math.random() - 0.5) * shake);
    }
    ctx.clearRect(-20, -20, W + 40, H + 40);

    // background grid glow
    const grad = ctx.createRadialGradient(W / 2, H * 0.35, 40, W / 2, H * 0.35, W * 0.7);
    grad.addColorStop(0, 'rgba(124,196,255,0.06)');
    grad.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, W, H);

    // bricks
    for (const brick of bricks) {
      if (!brick.alive) continue;
      ctx.fillStyle = brick.color;
      ctx.globalAlpha = brick.hp < brick.maxHp ? 0.55 : 1;
      roundRect(brick.x, brick.y, brick.w, brick.h, 5);
      ctx.fill();
      ctx.globalAlpha = 1;
      if (brick.maxHp > 1) {
        ctx.strokeStyle = 'rgba(255,255,255,0.5)';
        ctx.lineWidth = 2;
        roundRect(brick.x + 1, brick.y + 1, brick.w - 2, brick.h - 2, 4);
        ctx.stroke();
      }
    }

    // particles
    for (const p of particles) {
      ctx.globalAlpha = Math.max(p.life, 0);
      ctx.fillStyle = p.color;
      ctx.beginPath();
      ctx.arc(p.x, p.y, 2.5, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;

    // powerups
    for (const p of powerups) {
      ctx.fillStyle = p.type === 'wide' ? '#7cc4ff' : '#ff8fb1';
      roundRect(p.x - 16, p.y - 9, 32, 18, 6);
      ctx.fill();
      ctx.fillStyle = '#0a0714';
      ctx.font = 'bold 10px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(p.type === 'wide' ? 'WIDE' : 'x3', p.x, p.y + 1);
    }

    // paddle
    const pg = ctx.createLinearGradient(paddle.x, 0, paddle.x + paddle.w, 0);
    pg.addColorStop(0, '#7bf1a8');
    pg.addColorStop(1, '#4fd1ff');
    ctx.fillStyle = pg;
    roundRect(paddle.x, paddle.y, paddle.w, paddle.h, 7);
    ctx.fill();

    // balls
    for (const b of balls) {
      ctx.beginPath();
      ctx.fillStyle = '#fff';
      ctx.shadowColor = '#7cc4ff';
      ctx.shadowBlur = 12;
      ctx.arc(b.x, b.y, b.r, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;
    }

    if (running && !launched) {
      ctx.fillStyle = 'rgba(242,238,252,0.6)';
      ctx.font = '13px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('Click or press Space to launch', W / 2, H - 60);
    }

    ctx.restore();
  }

  function roundRect(x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  // ---------- loop ----------
  function loop() {
    if (!running) return;
    updatePaddle();
    updateBalls();
    updatePowerups();
    updateParticles();
    draw();
    requestAnimationFrame(loop);
  }

  // initial idle render
  resetPaddle();
  balls = [makeBall(true)];
  bricks = []; powerups = []; particles = []; shake = 0;
  buildBricks();
  draw();
})();
