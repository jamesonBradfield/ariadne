#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_new_initial_values() {
        let entity = Entity::new();
        assert_eq!(entity.health, 100.0);
        assert_eq!(entity.armor, 50.0);
        assert!(!entity.is_dead);
        assert_eq!(entity.max_health, 100.0);
    }

    #[test]
    fn test_heal_increases_health() {
        let mut entity = Entity::new();
        entity.heal(20.0);
        assert_eq!(entity.health, 120.0);
    }

    #[test]
    fn test_heal_exceeds_max_health() {
        let mut entity = Entity::new();
        entity.heal(150.0);
        assert_eq!(entity.health, 100.0);
    }

    #[test]
    fn test_take_damage_less_than_armor() {
        let mut entity = Entity::new();
        entity.take_damage(30.0);
        assert_eq!(entity.health, 100.0);
        assert!(!entity.is_dead);
    }

    #[test]
    fn test_take_damage_equal_to_armor() {
        let mut entity = Entity::new();
        entity.take_damage(50.0);
        assert_eq!(entity.health, 100.0);
        assert!(!entity.is_dead);
    }

    #[test]
    fn test_take_damage_more_than_armor() {
        let mut entity = Entity::new();
        entity.take_damage(60.0);
        assert_eq!(entity.health, 90.0);
        assert!(!entity.is_dead);
    }

    #[test]
    fn test_take_damage_kills_entity() {
        let mut entity = Entity::new();
        entity.take_damage(150.0);
        assert_eq!(entity.health, 0.0);
        assert!(entity.is_dead);
    }

    #[test]
    fn test_take_damage_beyond_zero() {
        let mut entity = Entity::new();
        entity.take_damage(200.0);
        assert_eq!(entity.health, 0.0);
        assert!(entity.is_dead);
    }
}