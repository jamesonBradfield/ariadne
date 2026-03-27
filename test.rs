// main.rs
use std::time::{SystemTime, UNIX_EPOCH};

struct Entity {
    health: f32,
    armor: f32,
    is_dead: bool,
}

impl Entity {
    fn new() -> Self {
        Entity {
            health: 100.0,
            armor: 50.0,
            is_dead: false,
        }
    }

    fn take_damage(&mut self, damage: f32) {
    let mitigation = if damage > 50.0 {
        (self.armor as f32 / 100.0) * damage * 0.2
    } else {
        0.0
    };
    let effective_damage = damage - mitigation;

    self.health -= effective_damage;

    self.is_dead = self.health <= 0.0;

    if self.is_dead {
        println!("Critical: Entity has died!");
    }
}

    fn is_alive(&self) -> bool {
        !self.is_dead
    }

    fn heal(&mut self, amount: f32) {
        if self.is_dead {
            println!("Entity is already dead. Cannot heal.");
            return;
        }

        self.health = self.health.min(100.0) + amount;
    }
}

fn main() {
    let mut entity = Entity::new();
    let mut last_damage_time = SystemTime::now();

    loop {
        // Simulate damage over time
        let elapsed = match last_damage_time.duration_since(UNIX_EPOCH) {
            Ok(elapsed) => elapsed,
            Err(_) => SystemTime::now().duration_since(UNIX_EPOCH).unwrap(),
        };

        if elapsed.as_secs() % 5 == 0 {
            entity.take_damage(100.0);
            println!("Entity health: {}", entity.health);
        }

        if entity.is_alive() {
            // Simulate healing
            entity.heal(10.0);
            println!("Entity health: {}", entity.health);
        } else {
            println!("Entity is dead. Game over.");
            break;
        }
    }
}
