pub struct Entity {
    pub health: f32,
    pub armor: f32,
    pub is_dead: bool,
}

impl Entity {
    pub fn new() -> Self {
        Self { health: 100.0, armor: 50.0, is_dead: false }
    }
    pub fn take_damage(&mut self, damage: f32) {
        self.health -= damage;
    }
}
