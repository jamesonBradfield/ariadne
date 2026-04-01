// main.rs

struct Entity {
    pub health: f32,
    pub armor: f32,
    pub is_dead: bool,
}

impl Entity {
    pub fn new() -> Self {
        Self {
            health: 100.0,
            armor: 50.0,
            is_dead: false,
        }
    }

    pub fn take_damage(&mut self, damage: f32) -> bool {
        if self.is_dead {
            return false;
        }

        let mitigation = damage * (self.armor / (self.armor + 100.0));
        let effective_damage = damage - mitigation;
        
        self.health -= effective_damage;

        if self.health <= 0.0 {
            self.health = 0.0;
            self.is_dead = true;
        }
        true
    }

    pub fn heal(&mut self, amount: f32) -> bool {
        if self.is_dead {
            return false;
        }
        self.health += amount;
        true
    }
}
