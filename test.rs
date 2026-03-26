struct Player {
    health: i32,
}

impl Player {
    fn take_damage(&mut self, amount: i32) {
        let mut damage = amount;
        if damage > 50 {
            damage -= (damage * 20) / 100;
        }
        self.health -= damage;
        if self.health <= 0 {
            self.health = 0;
            println!("CRITICAL: Player Dead!");
        } else {
            println!("Remaining health: {}", self.health);
        }
    }
}
